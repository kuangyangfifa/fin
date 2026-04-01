"""
Data migration script from old PyQt5 database to new Flask web database.

This script migrates data from the old finance.db (PyQt5 version) to
the new finance_web.db (Flask web version).

Usage:
    cd web
    python migrate_data.py

Before running:
    1. Make sure the old finance.db is in the parent directory
    2. Initialize the new web database by running the Flask app once
    3. Create an admin user using: flask create-admin
"""

import sqlite3
import os
from datetime import datetime


def migrate_data(old_db_path='../finance.db', new_db_path='finance_web.db'):
    """Migrate data from old database to new database."""

    if not os.path.exists(old_db_path):
        print(f"Error: Old database not found at {old_db_path}")
        print("Please ensure the old finance.db file is in the parent directory.")
        return False

    if not os.path.exists(new_db_path):
        print(f"Error: New database not found at {new_db_path}")
        print("Please run the Flask app first to initialize the new database.")
        return False

    # Connect to both databases
    old_conn = sqlite3.connect(old_db_path)
    old_conn.row_factory = sqlite3.Row

    new_conn = sqlite3.connect(new_db_path)
    new_conn.row_factory = sqlite3.Row

    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()

    try:
        # Check if there's an admin user in the new database
        new_cursor.execute("SELECT id FROM users LIMIT 1")
        admin_user = new_cursor.fetchone()

        if not admin_user:
            print("Error: No user found in new database.")
            print("Please create an admin user first using: flask create-admin")
            return False

        admin_user_id = admin_user['id']
        print(f"Using admin user ID: {admin_user_id}")

        # Migrate accounts
        print("\nMigrating accounts...")
        old_cursor.execute("SELECT id, account_name, initial_balance, created_at FROM accounts")
        accounts = old_cursor.fetchall()

        account_id_map = {}  # Map old IDs to new IDs

        for account in accounts:
            try:
                new_cursor.execute("""
                    INSERT INTO accounts (account_name, initial_balance, created_by, created_at)
                    VALUES (?, ?, ?, ?)
                """, (account['account_name'], account['initial_balance'], admin_user_id, account['created_at']))

                new_account_id = new_cursor.lastrowid
                account_id_map[account['id']] = new_account_id
                print(f"  Migrated account: {account['account_name']} (old ID: {account['id']}, new ID: {new_account_id})")
            except sqlite3.IntegrityError:
                # Account already exists, get its ID
                new_cursor.execute("SELECT id FROM accounts WHERE account_name = ?", (account['account_name'],))
                existing = new_cursor.fetchone()
                if existing:
                    account_id_map[account['id']] = existing['id']
                    print(f"  Account already exists: {account['account_name']} (skipped)")

        new_conn.commit()
        print(f"Migrated {len(accounts)} accounts")

        # Migrate transactions
        print("\nMigrating transactions...")
        old_cursor.execute("""
            SELECT id, date, account_id, summary, income, expense, balance_after, note1, note2, created_at
            FROM transactions
            ORDER BY date, id
        """)
        transactions = old_cursor.fetchall()

        migrated_count = 0
        skipped_count = 0

        for trans in transactions:
            old_account_id = trans['account_id']

            # Skip if account wasn't migrated
            if old_account_id not in account_id_map:
                print(f"  Warning: Skipping transaction {trans['id']} - account {old_account_id} not found")
                skipped_count += 1
                continue

            new_account_id = account_id_map[old_account_id]

            try:
                new_cursor.execute("""
                    INSERT INTO transactions
                    (date, account_id, summary, income, expense, balance_after, note1, note2, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trans['date'],
                    new_account_id,
                    trans['summary'],
                    trans['income'],
                    trans['expense'],
                    trans['balance_after'],
                    trans['note1'],
                    trans['note2'],
                    admin_user_id,
                    trans['created_at']
                ))
                migrated_count += 1
            except Exception as e:
                print(f"  Error migrating transaction {trans['id']}: {e}")
                skipped_count += 1

        new_conn.commit()
        print(f"Migrated {migrated_count} transactions")
        if skipped_count > 0:
            print(f"Skipped {skipped_count} transactions")

        # Verify balances
        print("\nVerifying account balances...")
        for old_account_id, new_account_id in account_id_map.items():
            # Calculate balance in old database
            old_cursor.execute("""
                SELECT COALESCE(SUM(income - expense), 0) as total_change
                FROM transactions
                WHERE account_id = ?
            """, (old_account_id,))
            old_result = old_cursor.fetchone()

            old_cursor.execute("SELECT initial_balance FROM accounts WHERE id = ?", (old_account_id,))
            old_account = old_cursor.fetchone()
            old_balance = old_account['initial_balance'] + (old_result['total_change'] if old_result else 0)

            # Calculate balance in new database
            new_cursor.execute("""
                SELECT COALESCE(SUM(income - expense), 0) as total_change
                FROM transactions
                WHERE account_id = ?
            """, (new_account_id,))
            new_result = new_cursor.fetchone()

            new_cursor.execute("SELECT initial_balance FROM accounts WHERE id = ?", (new_account_id,))
            new_account = new_cursor.fetchone()
            new_balance = new_account['initial_balance'] + (new_result['total_change'] if new_result else 0)

            status = "✓" if abs(old_balance - new_balance) < 0.01 else "✗"
            print(f"  {status} {new_account['account_name']}: {old_balance:.2f} -> {new_balance:.2f}")

        print("\nMigration completed successfully!")
        return True

    except Exception as e:
        print(f"\nError during migration: {e}")
        new_conn.rollback()
        return False

    finally:
        old_conn.close()
        new_conn.close()


def recalculate_all_balances():
    """Recalculate all transaction balances in the new database."""
    print("\nRecalculating all balances...")

    conn = sqlite3.connect('finance_web.db')
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, initial_balance FROM accounts")
        accounts = cursor.fetchall()

        for account_id, initial_balance in accounts:
            cursor.execute("""
                SELECT id, income, expense
                FROM transactions
                WHERE account_id = ?
                ORDER BY date, id
            """, (account_id,))

            transactions = cursor.fetchall()
            current_balance = initial_balance

            for trans_id, income, expense in transactions:
                current_balance = current_balance + income - expense
                cursor.execute("""
                    UPDATE transactions SET balance_after = ? WHERE id = ?
                """, (current_balance, trans_id))

            print(f"  Recalculated balances for account ID {account_id}")

        conn.commit()
        print("Balance recalculation completed!")

    except Exception as e:
        print(f"Error recalculating balances: {e}")
        conn.rollback()

    finally:
        conn.close()


if __name__ == '__main__':
    import sys

    print("=" * 60)
    print("Finance Database Migration Tool")
    print("=" * 60)
    print()

    if len(sys.argv) > 1 and sys.argv[1] == '--recalc':
        recalculate_all_balances()
    else:
        print("This will migrate data from ../finance.db to finance_web.db")
        print()

        response = input("Continue? (yes/no): ")
        if response.lower() == 'yes':
            if migrate_data():
                recalculate_all_balances()
        else:
            print("Migration cancelled.")
