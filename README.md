# Bank Statement Analyzer
A personal finance analysis tool that imports bank statements into MySQL 
and provides a natural language chat interface powered by a local LLM via Ollama.
The main idea is that anyone can upload their banking/spending data and be able to 
extract meaningful insights from it by just asking natural lnaguage questions. 
Everything is designed to be ran locally to ensure data privacy. This does sacrifice 
compute speed and ability to use more advanced LLMs but a small price to pay to keep
your spending/bank data private. 

## Setup
### Prerequisites
- Python 3.14+
- MySQL 8.0+
- Ollama (https://ollama.com)

### Usage
- Import transactions: via MySQL's Data Import Wizard 
- To create data for merchants, transaction category, etc. use: python Transactions_description_scraper.py
- Fill in merchants/missing data: python fill_merchants.py
- Run chat interface: python -m streamlit run chat_db.py. This is the interactable chat interface that will allow you to ask natural language questions about your data. 

### File Notes:
- The Transactions_description_scraper.py file runs very slowly on a CPU and is also not very accurate. This is a work in progress to make it perform better.
This py file uses a LLM to use the transaction description to classify a transaction's merchant, spending category, and transaction type. A stronger LLM
could be used but requires some powerful hardware. 
- The fill_merchants.py file was created in an effort to fill in some of the missing values, but also runs quite slowly on a CPU. It also uses an LLM to fill in
- the merchant information from the description. A larger LLM would most likely work better but comes at the expense of higher compute.

- ### Importing Transactions
1. Place your transactions CSV in the same folder as `Transactions.py`
2. Update the config block at the top of `Transactions.py` with your CSV filename and column names
3. Make sure Ollama is running in the background
4. Run:
```bash
python Transactions.py
```
5. Import the output CSVs into MySQL Workbench in this order:
   - `out_categories.csv` → categories table
   - `out_merchants.csv` → merchants table
   - `out_transactions.csv` → transactions table

### Filling in Missing Merchants
If any transactions are missing merchant IDs after import:
```bash
python fill_merchants.py
```

### Running the Chat Interface
1. Make sure Ollama is running
2. Make sure MySQL is running
3. Run:
```bash
python -m streamlit run chat_db.py
```
4. A browser tab will automatically open at `http://localhost:8501`
5. Type questions about your finances in plain English or use the example questions in the sidebar

### Stopping the Chat Interface
Press `Ctrl+C` in the terminal to stop the Streamlit server.

## Example Questions
- How much did I spend on dining last month?
- What are my top 5 merchants by spending?
- How much did I spend in total by category?
- What was my total spending in January 2026?
- How much did I spend vs earn each month?

## Some small technical nuances 
- Negative amounts represent debits (money spent)
- Positive amounts represent credits (money received)
- `balance_after` is NULL for credit card accounts
- Transactions marked as `is_transfer = 1` are excluded from spending totals to avoid double counting
