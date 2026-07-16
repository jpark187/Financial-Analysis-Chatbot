import streamlit as st
import mysql.connector
import ollama
import json
import re

# =========================================
# CONFIGURATION — edit these before running
# =========================================

DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",          # your MySQL username
    #"password": "your MySQL password",
    "database": "bank_statements"
}

MODEL = "llama3.1"

# =========================================
# SCHEMA CONTEXT
# =========================================

SCHEMA = """
You are a MySQL expert helping analyze personal bank statement data.

Database schema:
CREATE TABLE accounts (
    account_id   INT PRIMARY KEY,
    account_name VARCHAR(100),
    account_type VARCHAR(50),
    bank_name    VARCHAR(100),
    currency     VARCHAR(10)
);

CREATE TABLE categories (
    category_id    INT PRIMARY KEY,
    category_name  VARCHAR(100),
    parent_category VARCHAR(100)
);

CREATE TABLE merchants (
    merchant_id       INT PRIMARY KEY,
    merchant_name     VARCHAR(150),
    merchant_category VARCHAR(100)
);

CREATE TABLE transactions (
    transaction_id   INT PRIMARY KEY,
    account_id       INT,
    transaction_date DATE,
    amount           DECIMAL(12,2),
    description      VARCHAR(255),
    transaction_type VARCHAR(10),
    category_id      INT,
    merchant_id      INT,
    balance_after    DECIMAL(12,2),
    FOREIGN KEY (account_id)  REFERENCES accounts(account_id),
    FOREIGN KEY (category_id) REFERENCES categories(category_id),
    FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id)
);

Important notes:
- Negative amounts are debits (money spent)
- Positive amounts are credits (money received)
- transaction_type is 'debit' or 'credit'
- balance_after is NULL for credit card accounts and NOT NULL for checking accounts
- To avoid double counting, spending queries should exclude transfer transactions
- Credit card payments from checking accounts are transfers, not spending
- is_transfer = 1 marks transactions that are inter-account transfers and should be excluded from spending totals
- Dates are in YYYY-MM-DD format


Rules for generating SQL:
- Always use JOIN instead of subqueries where possible
- Always alias tables (e.g. t for transactions, c for categories)
- For spending queries, filter WHERE t.amount < 0
- For income queries, filter WHERE t.amount > 0
- Use SUM(t.amount) for totals
- Use DATE_FORMAT(t.transaction_date, '%Y-%m') for monthly grouping
- Always include AND t.is_transfer = 0 in WHERE clause for any spending or income queries to exclude transfers
- Always return a clean readable result
"""

# =========================================
# DATABASE CONNECTION
# =========================================

def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SET SESSION sql_mode= ''")
    conn.commit()
    cursor.close()
    return conn

def run_query(sql):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

# =========================================
# SQL GENERATION
# =========================================

def generate_sql(question):
    prompt = f"""{SCHEMA}

User question: {question}

Generate a single valid MySQL SELECT query to answer this question.
Return ONLY the raw SQL query with no explanation, no markdown, no backticks.
Always include all non-aggregated columns in the GROUP BY clause if using aggregation.
Never SELECT a column without aggregating it or including it in GROUP BY.
When using GROUP BY, every column in SELECT must either be aggregated (SUM, COUNT, AVG, etc.) or included in the GROUP BY clause."""

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0,
                 "num_predict":200
                 }
    )
    raw = response["message"]["content"].strip()
    # Strip any markdown fences if model adds them anyway
    raw = re.sub(r'```sql|```', '', raw).strip()
    return raw

def validate_results(results, max_row=20):
    """Cap reuslts sent to summarizer to avoid overwhelming the model."""
    if len(results) > max_row:
        return results[:max_row], f"Showing top {max_row} of {len(results)} results"
    return results, None

def summarize_results(question, sql, results):
    """Ask Ollama to summarize the results in plain English."""
    if not results:
        return "No results found for that query."

    prompt = f"""The user asked: "{question}"

The query results are:
{json.dumps(results, indent=2, default=str)}

STRICT RULES:
Only reference numbers, merchants, dates, and amounts that appear EXACTLY in the result above.
Do not invent, estimate, or assume any details not present in the results.
Do not reference any transactions, merchants, or amounts not above.
If the results are limited (e.g. TOP 5), do not mention anything outside of that list. 
Summarize the results in 1-3 clear, friendly sentences as if you're a personal finance assistant.
Don't mention SQL or technical details. Just answer the question naturally.

Summary:"""   
    
    response = ollama.chat(
        model="phi3:mini",
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0, "num_ctx":2048}
    )

    raw = response["message"]["content"].strip()
    raw = raw.replace('\u2019', "'")   # curly apostrophe
    raw = raw.replace('\u2018', "'")   # curly open quote
    raw = raw.replace('\u201c', '"')   # curly open double quote
    raw = raw.replace('\u201d', '"')   # curly close double quote
    raw = raw.replace('\u2013', '-')   # en dash
    raw = raw.replace('\u2014', '--')  # em dash
    raw = raw.replace('\xa0', ' ')     # non-breaking space
    return raw

# =========================================
# STREAMLIT UI
# =========================================

st.set_page_config(
    page_title="Bank Statement Assistant",
    page_icon="💰",
    layout="wide"
)

st.title("💰 Bank Statement Assistant")
st.caption("Ask questions about your transactions in plain English")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

if "sql_history" not in st.session_state:
    st.session_state.sql_history = []

# Sidebar with example questions
with st.sidebar:
    st.header("Example Questions")
    examples = [
        "How much did I spend on dining last month?",
        "What are my top 5 merchants by spending?",
        "How much did I spend in total by category?",
        "What was my total spending in January 2026?",
        "How much did I spend vs earn each month?",
        "What is my average monthly spending?",
        "Which month did I spend the most?",
        "How much did I spend at grocery stores?",
        "What are my top 10 most expensive transactions?",
        "How much did I spend on subscriptions?",
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state.pending_question = example

    st.divider()
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.sql_history = []
    
    st.divider()
    st.caption("Always verify the summary against the data table. AI summaries may be inaccurate. If the summary seems off, check the SQL query and results table.")

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "dataframe" in msg:
            st.dataframe(msg["dataframe"], use_container_width=True)
        if "sql" in msg:
            with st.expander("View SQL query"):
                st.code(msg["sql"], language="sql")

# Handle example question clicks
question = None
if "pending_question" in st.session_state:
    question = st.session_state.pending_question
    del st.session_state.pending_question

# Chat input
user_input = st.chat_input("Ask a question about your finances...")
if user_input:
    question = user_input

# Process question
if question:
    # Display user message
    with st.chat_message("user"):
        st.write(question)
    st.session_state.messages.append({"role": "user", "content": question})

    # Generate and run query
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Generate SQL
                sql = generate_sql(question)

                # Run query
                results = run_query(sql)

                if results:
                    import pandas as pd
                    df = pd.DataFrame(results)

                    capped_results, cap_note = validate_results(results)

                    # Fix 4: show table FIRST so user can verify before reading summary
                    st.dataframe(df, use_container_width=True)

                    # Fix 1: summarize only from capped results
                    summary = summarize_results(question, sql, capped_results)

                    if cap_note:
                        summary += f"\n\n_{cap_note}_"

                    # Summarize in plain English
                    st.markdown(summary)

                    # Show results table
                    st.dataframe(df, use_container_width=True)

                    # Store in history
                    msg = {
                        "role": "assistant",
                        "content": summary,
                        "dataframe": df,
                        "sql": sql
                    }
                else:
                    summary = "No results found for that question. Try rephrasing it."
                    st.markdown(summary)
                    msg = {"role": "assistant", "content": summary, "sql": sql}

                with st.expander("View SQL query"):
                    st.code(sql, language="sql")

                st.session_state.messages.append(msg)

            except Exception as e:
                error_msg = f"Something went wrong: {str(e)}\n\nTry rephrasing your question."
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg
                })