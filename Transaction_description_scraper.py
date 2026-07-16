import ollama
import pandas as pd
import json
import re
import time
from pathlib import Path

# =========================================
# CONFIGURATION — edit these before running
# =========================================

#INPUT_CSV             = Link the file path to your CSV files.  
#OUTPUT_TRANSACTIONS   = Link the file path to your CSV files.  
#OUTPUT_MERCHANTS      = Link the file path to your CSV files.  
#OUTPUT_CATEGORIES     = Link the file path to your CSV files.  

MODEL                 = "mistral"
DESCRIPTION_COLUMN    = "description"
AMOUNT_COLUMN         = "amount"
DATE_COLUMN           = "transaction_date"
BALANCE_COLUMN        = "balance_after"   # set to None if not present
ACCOUNT_ID            = 1                 # ignored if account_id already in CSV
BATCH_SIZE            = 25               # number of transactions per API call

# Set these to True if the column already exists in your CSV
HAS_ACCOUNT_ID        = True
HAS_TRANSACTION_ID    = True

CATEGORIES = [
    "Dining",
    "Groceries",
    "Gas/Auto",
    "Retail/Shopping",
    "Income/Deposits",
    "Utilities",
    "Healthcare",
    "Travel",
    "Entertainment",
    "Subscriptions",
    "Transfers",
    "Fees/Interest",
    "Other"
]

# Category -> parent mapping for your categories table
PARENT_MAP = {
    "Dining":           "Food",
    "Groceries":        "Food",
    "Gas/Auto":         "Transportation",
    "Retail/Shopping":  "Shopping",
    "Income/Deposits":  "Income",
    "Utilities":        "Bills",
    "Healthcare":       "Health",
    "Travel":           "Transportation",
    "Entertainment":    "Leisure",
    "Subscriptions":    "Bills",
    "Transfers":        "Finance",
    "Fees/Interest":    "Finance",
    "Other":            None
}

# =========================================
# PROMPTS
# =========================================

def build_batch_prompt(descriptions):
    numbered = "\n".join([f"{i+1}. {d}" for i, d in enumerate(descriptions)])
    return f"""You are a bank transaction categorizer and merchant extractor.

For each transaction below return a JSON array. Each element must have:
- "merchant_name": clean merchant name, null if no merchant
- "merchant_category": short merchant type e.g. "Coffee Shop", null if no merchant
- "category": exactly one of: {", ".join(CATEGORIES)}

Examples of good output:
[
  {{"merchant_name": "Chipotle", "merchant_category": "Fast Food", "category": "Dining"}},
  {{"merchant_name": "Shell", "merchant_category": "Gas Station", "category": "Gas/Auto"}},
  {{"merchant_name": null, "merchant_category": null, "category": "Income/Deposits"}}
]

Transactions:
{numbered}

Return ONLY a raw JSON array with exactly {len(descriptions)} elements, no markdown, no explanation."""

# =========================================
# JSON EXTRACTION
# =========================================

def extract_json_array(text):
    text = re.sub(r'```json|```', '', text).strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON array found in response: {text}")

# =========================================
# BATCH CATEGORIZATION
# =========================================

def categorize_batch(descriptions, retries=2):
    for attempt in range(retries + 1):
        try:
            response = ollama.chat(
                model=MODEL,
                messages=[{'role': 'user', 'content': build_batch_prompt(descriptions)}],
                options={"temperature": 0.1}
            )
            text    = response['message']['content']
            results = extract_json_array(text)
            if len(results) != len(descriptions):
                raise ValueError(f"Expected {len(descriptions)} results, got {len(results)}")
            return results
        except Exception as e:
            if attempt < retries:
                print(f"\n  ⚠ Batch attempt {attempt+1} failed: {e} — retrying...")
                time.sleep(1)
            else:
                print(f"\n  ⚠ Batch failed after {retries+1} attempts — falling back to 'Other'")
                return [{"merchant_name": None, "merchant_category": None, "category": "Other"}] * len(descriptions)

# =========================================
# LOOKUP TABLES (built dynamically)
# =========================================

def get_or_create_category(name, category_lookup):
    if name not in category_lookup:
        new_id = len(category_lookup) + 1
        category_lookup[name] = {
            "category_id":    new_id,
            "category_name":  name,
            "parent_category": PARENT_MAP.get(name)
        }
    return category_lookup[name]["category_id"]

def get_or_create_merchant(name, merchant_category, merchant_lookup):
    if name not in merchant_lookup:
        new_id = len(merchant_lookup) + 1
        merchant_lookup[name] = {
            "merchant_id":       new_id,
            "merchant_name":     name,
            "merchant_category": merchant_category
        }
    return merchant_lookup[name]["merchant_id"]

# =========================================
# MAIN
# =========================================

def main():
    # --- Load CSV ---
    input_path = Path(INPUT_CSV)
    if not input_path.exists():
        print(f"❌ File not found: {INPUT_CSV}")
        print("   Check the path in your config block.")
        return

    df = pd.read_csv(input_path)
    print(f"✅ Loaded {len(df)} rows from {INPUT_CSV}")

    if DESCRIPTION_COLUMN not in df.columns:
        print(f"❌ Column '{DESCRIPTION_COLUMN}' not found.")
        print(f"   Columns detected: {list(df.columns)}")
        return

    # --- Check Ollama ---
    try:
        ollama.list()
        print(f"✅ Ollama running — model: {MODEL}")
        print(f"✅ Batch size: {BATCH_SIZE} transactions per call\n")
    except Exception:
        print("❌ Ollama not running. Open a terminal and run: ollama serve")
        return

    # --- Lookup tables ---
    category_lookup = {}
    merchant_lookup = {}

    # Pre-populate categories so IDs are stable
    for cat in CATEGORIES:
        get_or_create_category(cat, category_lookup)

    # --- Process in batches ---
    transaction_type_list = []
    category_id_list      = []
    merchant_id_list      = []
    total        = len(df)
    descriptions = df[DESCRIPTION_COLUMN].astype(str).str.strip().tolist()
    start_time   = time.time()

    for batch_start in range(0, total, BATCH_SIZE):
        batch_descs = descriptions[batch_start:batch_start + BATCH_SIZE]
        batch_end   = min(batch_start + BATCH_SIZE, total)
        print(f"[{batch_start+1}-{batch_end}/{total}] Processing batch...", end=" → ")

        results = categorize_batch(batch_descs)

        for i, result in enumerate(results):
            row_idx = batch_start + i

            merchant_name     = result.get('merchant_name') or None
            merchant_category = result.get('merchant_category') or None
            category          = result.get('category')
            if category not in CATEGORIES:
                category = 'Other'

            # Derive transaction_type from amount sign
            try:
                amount = float(str(df.iloc[row_idx][AMOUNT_COLUMN]).replace(',', '').replace('$', ''))
                t_type = 'credit' if amount > 0 else 'debit'
            except Exception:
                t_type = 'debit'

            cat_id   = get_or_create_category(category, category_lookup)
            merch_id = get_or_create_merchant(merchant_name, merchant_category, merchant_lookup) if merchant_name else None

            transaction_type_list.append(t_type)
            category_id_list.append(cat_id)
            merchant_id_list.append(merch_id)

        # Estimate time remaining
        elapsed     = time.time() - start_time
        rate        = batch_end / elapsed
        remaining   = (total - batch_end) / rate if rate > 0 else 0
        print(f"done ✓  ({batch_end}/{total}) — ~{int(remaining)}s remaining")

    # --- Build final transactions dataframe ---
    if not HAS_ACCOUNT_ID:
        df['account_id'] = ACCOUNT_ID
    else:
        print("\nℹ️  account_id already present — skipping auto-assign")

    if HAS_TRANSACTION_ID and 'transaction_id' not in df.columns:
        print("⚠️  HAS_TRANSACTION_ID is True but no transaction_id column found — check column name")

    df['transaction_type'] = transaction_type_list
    df['category_id']      = category_id_list
    df['merchant_id']      = merchant_id_list

    # Rename columns to match schema
    rename_map = {}
    if DATE_COLUMN in df.columns:
        rename_map[DATE_COLUMN] = 'transaction_date'
    if BALANCE_COLUMN and BALANCE_COLUMN in df.columns:
        rename_map[BALANCE_COLUMN] = 'balance_after'
    df.rename(columns=rename_map, inplace=True)

    # Final column order
    trans_cols = []
    if HAS_TRANSACTION_ID and 'transaction_id' in df.columns:
        trans_cols.append('transaction_id')
    trans_cols.append('account_id')
    trans_cols += ['transaction_date', 'amount', 'description',
                   'transaction_type', 'category_id', 'merchant_id']
    if 'balance_after' in df.columns:
        trans_cols.append('balance_after')
    trans_cols = [c for c in trans_cols if c in df.columns]

    # --- Build merchants and categories dataframes ---
    merchants_df  = pd.DataFrame(merchant_lookup.values())[
        ['merchant_id', 'merchant_name', 'merchant_category']
    ]
    categories_df = pd.DataFrame(category_lookup.values())[
        ['category_id', 'category_name', 'parent_category']
    ]

    # --- Save all three CSVs ---
    df[trans_cols].to_csv(OUTPUT_TRANSACTIONS, index=False)
    merchants_df.to_csv(OUTPUT_MERCHANTS,      index=False)
    categories_df.to_csv(OUTPUT_CATEGORIES,    index=False)

    # --- Summary ---
    total_time = int(time.time() - start_time)
    print(f"\n{'='*55}")
    print(f"✅ Finished in {total_time}s")
    print(f"\nOutput files saved:")
    print(f"   📄 {OUTPUT_TRANSACTIONS}  ({len(df)} rows)")
    print(f"   📄 {OUTPUT_MERCHANTS}     ({len(merchants_df)} unique merchants)")
    print(f"   📄 {OUTPUT_CATEGORIES}    ({len(categories_df)} categories)")
    print(f"\nCategory breakdown:")
    cat_name_map = {v['category_id']: k for k, v in category_lookup.items()}
    for cat_id, count in pd.Series(category_id_list).value_counts().items():
        name = cat_name_map.get(cat_id, 'Unknown')
        bar  = '█' * int(count / total * 30)
        print(f"  {name:<22} {bar} {count}")
    other_count = sum(1 for c in category_id_list if cat_name_map.get(c) == 'Other')
    if other_count > 0:
        print(f"\n⚠  {other_count} rows landed in 'Other' — review these manually.")
    print(f"\n💡 MySQL import order:")
    print(f"   1. categories   ({OUTPUT_CATEGORIES})")
    print(f"   2. merchants    ({OUTPUT_MERCHANTS})")
    print(f"   3. transactions ({OUTPUT_TRANSACTIONS})")

if __name__ == "__main__":
    main()