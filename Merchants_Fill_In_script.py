import ollama
#import mysql.connector
import pymysql
import json
import re
import time

# =========================================
# CONFIGURATION — edit these before running
# =========================================

DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    #"password": "your MySQL password",
    "database": "bank_statements"
}

MODEL      = "mistral"
BATCH_SIZE = 15

CATEGORIES = [
    "Dining", "Groceries", "Gas/Auto", "Retail/Shopping",
    "Income/Deposits", "Utilities", "Healthcare", "Travel",
    "Entertainment", "Subscriptions", "Transfers", "Fees/Interest", "Other"
]

# =========================================
# DATABASE HELPERS
# =========================================

def get_connection():
    #return mysql.connector.connect(**DB_CONFIG)
    return pymysql.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        cursorclass=pymysql.cursors.DictCursor
    )

def get_null_merchant_transactions():
    """Pull all transactions where merchant_id is NULL."""
    conn = get_connection()
    #cursor = conn.cursor(dictionary=True)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT transaction_id, description, amount
        FROM transactions
        WHERE merchant_id IS NULL
        ORDER BY transaction_id
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    print(f"✅ Found {len(rows)} transactions with NULL merchant_id")
    return rows

def get_existing_merchants():
    """Load all existing merchants from the database into a lookup dict."""
    conn = get_connection()
    #cursor = conn.cursor(dictionary=True)
    cursor = conn.cursor()
    cursor.execute("SELECT merchant_id, merchant_name, merchant_category FROM merchants")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    # Key by lowercase name for case-insensitive matching
    lookup = {r['merchant_name'].lower(): r for r in rows}
    print(f"✅ Loaded {len(lookup)} existing merchants")
    return lookup

def get_next_merchant_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(merchant_id) AS max_id FROM merchants")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    result = row['max_id'] if row else None
    return (result or 0) + 1

def insert_merchant(merchant_id, merchant_name, merchant_category):
    """Insert a new merchant into the merchants table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO merchants (merchant_id, merchant_name, merchant_category)
        VALUES (%s, %s, %s)
    """, (merchant_id, merchant_name, merchant_category))
    conn.commit()
    cursor.close()
    conn.close()

def update_transaction_merchant(transaction_id, merchant_id):
    """Update a transaction's merchant_id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE transactions
        SET merchant_id = %s
        WHERE transaction_id = %s
    """, (merchant_id, transaction_id))
    conn.commit()
    cursor.close()
    conn.close()

# =========================================
# PROMPT
# =========================================

def build_batch_prompt(descriptions):
    numbered = "\n".join([f"{i+1}. {d}" for i, d in enumerate(descriptions)])
    return f"""You are a bank transaction merchant extractor.

For each transaction description below, return a JSON array. Each element must have:
- "merchant_name": clean readable merchant name (e.g. "Chipotle", "Amazon", "Shell"). 
  Strip location info, IDs, and noise. 
  Use null if there is genuinely no merchant (e.g. bank transfers, payroll deposits).
- "merchant_category": short merchant type (e.g. "Fast Food", "Online Retail", "Gas Station").
  Use null if merchant_name is null.

Examples:
[
  {{"merchant_name": "Chipotle", "merchant_category": "Fast Food"}},
  {{"merchant_name": "Shell", "merchant_category": "Gas Station"}},
  {{"merchant_name": null, "merchant_category": null}},
  {{"merchant_name": "Netflix", "merchant_category": "Streaming"}}
]

Transactions:
{numbered}

Return ONLY a raw JSON array with exactly {len(descriptions)} elements, no markdown, no explanation."""

# =========================================
# BATCH PROCESSING
# =========================================

def extract_json_array(text):
    text = re.sub(r'```json|```', '', text).strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON array found: {text}")

def process_batch(descriptions, retries=2):
    for attempt in range(retries + 1):
        try:
            response = ollama.chat(
                model=MODEL,
                messages=[{'role': 'user', 'content': build_batch_prompt(descriptions)}],
                options={"temperature": 0.1}
            )
            results = extract_json_array(response['message']['content'])
            if len(results) != len(descriptions):
                raise ValueError(f"Expected {len(descriptions)} results, got {len(results)}")
            return results
        except Exception as e:
            if attempt < retries:
                print(f"\n  ⚠ Attempt {attempt+1} failed: {e} — retrying...")
                time.sleep(1)
            else:
                print(f"\n  ⚠ Batch failed — defaulting to null merchant")
                return [{"merchant_name": None, "merchant_category": None}] * len(descriptions)

# =========================================
# MAIN
# =========================================

def main():
    # --- Check Ollama ---
    try:
        ollama.list()
        print(f"✅ Ollama running — model: {MODEL}\n")
    except Exception:
        print("❌ Ollama not running. Run: ollama serve")
        return

    # --- Load data ---
    transactions  = get_null_merchant_transactions()
    if not transactions:
        print("✅ No NULL merchant_ids found — nothing to do!")
        return

    merchant_lookup = get_existing_merchants()
    next_id         = get_next_merchant_id()
    print(f"✅ Next available merchant_id: {next_id}\n")

    # --- Process in batches ---
    total        = len(transactions)
    descriptions = [t['description'] for t in transactions]
    start_time   = time.time()

    assigned     = 0
    created      = 0
    skipped      = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch_transactions = transactions[batch_start:batch_start + BATCH_SIZE]
        batch_descriptions = descriptions[batch_start:batch_start + BATCH_SIZE]
        batch_end          = min(batch_start + BATCH_SIZE, total)

        print(f"[{batch_start+1}-{batch_end}/{total}] Processing batch...", end=" → ")

        results = process_batch(batch_descriptions)

        for i, result in enumerate(results):
            transaction  = batch_transactions[i]
            merchant_name     = result.get('merchant_name')
            merchant_category = result.get('merchant_category')

            if not merchant_name:
                # No merchant for this transaction (transfer, deposit, etc.)
                skipped += 1
                continue

            # Normalize name for lookup
            name_lower = merchant_name.lower().strip()

            # Check if merchant already exists
            if name_lower in merchant_lookup:
                # Reuse existing merchant_id
                merchant_id = merchant_lookup[name_lower]['merchant_id']
            else:
                # Insert new merchant
                merchant_id = next_id
                next_id    += 1
                try:
                    insert_merchant(merchant_id, merchant_name, merchant_category)
                    merchant_lookup[name_lower] = {
                        'merchant_id':       merchant_id,
                        'merchant_name':     merchant_name,
                        'merchant_category': merchant_category
                    }
                    created += 1
                except Exception as e:
                    print(f"\n  ⚠ Could not insert merchant '{merchant_name}': {e}")
                    skipped += 1
                    continue

            # Update the transaction
            try:
                update_transaction_merchant(transaction['transaction_id'], merchant_id)
                assigned += 1
            except Exception as e:
                print(f"\n  ⚠ Could not update transaction {transaction['transaction_id']}: {e}")
                skipped += 1

        # Progress
        elapsed   = time.time() - start_time
        rate      = batch_end / elapsed if elapsed > 0 else 1
        remaining = int((total - batch_end) / rate)
        print(f"done ✓  ({batch_end}/{total}) — ~{remaining}s remaining")

    # --- Summary ---
    total_time = int(time.time() - start_time)
    print(f"\n{'='*55}")
    print(f"✅ Finished in {total_time}s")
    print(f"   Merchants assigned:    {assigned}")
    print(f"   New merchants created: {created}")
    print(f"   Skipped (no merchant): {skipped}")

    # --- Verify remaining NULLs ---
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE merchant_id IS NULL")
    remaining_nulls = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    print(f"   Remaining NULL merchant_ids: {remaining_nulls}")

if __name__ == "__main__":
    main()