-- =========================================
-- Bank Statement Analysis Database Schema (MySQL)
-- =========================================

CREATE SCHEMA bank_statements;
USE bank_statements;

-- 1. Accounts table
CREATE TABLE accounts (
    account_id      INT AUTO_INCREMENT PRIMARY KEY,
    account_name    VARCHAR(100) NOT NULL,
    account_type    VARCHAR(50) NOT NULL,        -- e.g. 'checking', 'savings', 'credit card'
    bank_name       VARCHAR(100),
    currency        VARCHAR(10) DEFAULT 'USD'
);

-- 2. Categories table
CREATE TABLE categories (
    category_id     INT AUTO_INCREMENT PRIMARY KEY,
    category_name   VARCHAR(100) NOT NULL UNIQUE,
    parent_category VARCHAR(100)                 -- optional: for grouping (e.g. 'Food' -> 'Groceries', 'Dining')
);

-- 3. Merchants table
CREATE TABLE merchants (
    merchant_id       INT AUTO_INCREMENT PRIMARY KEY,
    merchant_name     VARCHAR(150) NOT NULL UNIQUE,
    merchant_category VARCHAR(100)
);

-- 4. Transactions table (fact table)
CREATE TABLE transactions (
    transaction_id   INT AUTO_INCREMENT PRIMARY KEY,
    account_id       INT NOT NULL,
    transaction_date DATE NOT NULL,
    amount           DECIMAL(12,2) NOT NULL,
    description      VARCHAR(255),
    transaction_type VARCHAR(10),                -- 'debit' or 'credit'
    category_id      INT,
    merchant_id       INT,
    balance_after    DECIMAL(12,2),
    is_transfer     TINYINT(1),

    FOREIGN KEY (account_id)  REFERENCES accounts(account_id),
    FOREIGN KEY (category_id) REFERENCES categories(category_id),
    FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id)
);

-- =========================================
-- Helpful indexes for analysis queries
-- =========================================
CREATE INDEX idx_transactions_account_id  ON transactions(account_id);
CREATE INDEX idx_transactions_date        ON transactions(transaction_date);
CREATE INDEX idx_transactions_category_id ON transactions(category_id);
CREATE INDEX idx_transactions_merchant_id ON transactions(merchant_id);

# Use Data Import Wizard to import the data into the database