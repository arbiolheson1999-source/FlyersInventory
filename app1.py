from flask import Flask, render_template, request, redirect, jsonify
import psycopg2
import os

app = Flask(__name__)


def get_conn():
    return psycopg2.connect(
        host="localhost",
        database="flyers_db",
        user="postgres",
        password="marketing2026",
        port="5432"
    )

@app.route('/')
def index():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT b.id, b.name, COALESCE(SUM(s.remaining_quantity), 0) AS total_remaining
        FROM branches b
        LEFT JOIN branch_flyer_stock s ON b.id = s.branch_id
        GROUP BY b.id, b.name
        ORDER BY b.name
    """)
    branches = cur.fetchall()

    cur.execute("SELECT id, name FROM flyers ORDER BY name")
    flyers = cur.fetchall()

    selected_branch = request.args.get('branch')
    selected_quarter = request.args.get('quarter')
    selected_month = request.args.get('month')
    selected_year = request.args.get('year')

    summary_query = """
        SELECT b.name, d.quarter, SUM(d.quantity) AS total_quantity
        FROM distributions d
        JOIN branches b ON d.branch_id = b.id
        WHERE 1=1
    """

    params = []

    if selected_branch:
        summary_query += " AND d.branch_id = %s"
        params.append(int(selected_branch))

    if selected_quarter:
        summary_query += " AND d.quarter = %s"
        params.append(selected_quarter)

    if selected_month:
        summary_query += " AND EXTRACT(MONTH FROM d.date) = %s"
        params.append(int(selected_month))

    if selected_year:
        summary_query += " AND EXTRACT(YEAR FROM d.date) = %s"
        params.append(int(selected_year))

    summary_query += " GROUP BY b.name, d.quarter ORDER BY b.name"

    cur.execute(summary_query, params)
    summary = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'index.html',
        branches=branches,
        flyers=flyers,
        summary=summary
    )


@app.route('/add_stock', methods=['POST'])
def add_stock():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = int(request.form['branch'])
    flyer_id = int(request.form['flyer'])
    quantity = int(request.form['quantity'])

    try:
        cur.execute("""
            INSERT INTO branch_flyer_stock (branch_id, flyer_id, remaining_quantity)
            VALUES (%s, %s, %s)
            ON CONFLICT (branch_id, flyer_id)
            DO UPDATE SET remaining_quantity =
                branch_flyer_stock.remaining_quantity + EXCLUDED.remaining_quantity
        """, (branch_id, flyer_id, quantity))

        conn.commit()

    except Exception as e:
        conn.rollback()
        return f"Database error: {e}", 500

    finally:
        cur.close()
        conn.close()

    return redirect('/')


@app.route('/add', methods=['POST'])
def add():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = int(request.form['branch'])
    flyer_id = int(request.form['flyer'])
    quantity = int(request.form['quantity'])
    month = int(request.form['month'])
    year = int(request.form['year'])

    if month in [1, 2, 3]:
        quarter = 'Q1'
    elif month in [4, 5, 6]:
        quarter = 'Q2'
    elif month in [7, 8, 9]:
        quarter = 'Q3'
    else:
        quarter = 'Q4'

    try:
        cur.execute("""
            SELECT remaining_quantity
            FROM branch_flyer_stock
            WHERE branch_id = %s AND flyer_id = %s
        """, (branch_id, flyer_id))

        row = cur.fetchone()

        if not row:
            conn.rollback()
            return "No stock for this branch and flyer.", 400

        remaining = row[0]

        if quantity > remaining:
            conn.rollback()
            return f"Cannot distribute {quantity}. Only {remaining} remaining.", 400

        cur.execute("""
            INSERT INTO distributions (branch_id, flyer_id, quantity, quarter, date)
            VALUES (%s, %s, %s, %s, MAKE_DATE(%s, %s, 1))
        """, (branch_id, flyer_id, quantity, quarter, year, month))

        cur.execute("""
            UPDATE branch_flyer_stock
            SET remaining_quantity = remaining_quantity - %s
            WHERE branch_id = %s AND flyer_id = %s
        """, (quantity, branch_id, flyer_id))

        conn.commit()

    except Exception as e:
        conn.rollback()
        return f"Database error: {e}", 500

    finally:
        cur.close()
        conn.close()

    return redirect('/')

@app.route('/flyer/<int:flyer_id>')
def flyer_page(flyer_id):
    conn = get_conn()
    cur = conn.cursor()

    # Get flyer
    cur.execute("SELECT id, name FROM flyers WHERE id = %s", (flyer_id,))
    flyer = cur.fetchone()

    if not flyer:
        cur.close()
        conn.close()
        return "Flyer not found", 404

    # Get all branches for dropdown
    cur.execute("SELECT id, name FROM branches ORDER BY name")
    branches = cur.fetchall()

    # Get selected branch from URL
    selected_branch = request.args.get('branch')

    stock = None
    records = []    

    # ONLY RUN THESE IF USER SELECTED A BRANCH
    if selected_branch:

        # Remaining stock (single branch only)
        cur.execute("""
            SELECT COALESCE(remaining_quantity, 0)
            FROM branch_flyer_stock
            WHERE branch_id = %s AND flyer_id = %s
        """, (int(selected_branch), flyer_id))

        row = cur.fetchone()
        stock = row[0] if row else 0

        # Records for selected branch only
        cur.execute("""
            SELECT d.id, b.name, f.name, d.quantity, d.quarter, d.date
            FROM distributions d
            JOIN branches b ON d.branch_id = b.id
            JOIN flyers f ON d.flyer_id = f.id
            WHERE d.flyer_id = %s AND d.branch_id = %s
            ORDER BY d.date DESC, d.id DESC
        """, (flyer_id, int(selected_branch)))

        records = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'flyer_page.html',
        flyer=flyer,
        branches=branches,
        selected_branch=selected_branch,
        stock=stock,
        records=records
    )
@app.route('/delete', methods=['POST'])
def delete():
    conn = get_conn()
    cur = conn.cursor()

    record_id = int(request.form['record_id'])

    try:
        cur.execute("""
            SELECT branch_id, flyer_id, quantity
            FROM distributions
            WHERE id = %s
        """, (record_id,))

        data = cur.fetchone()

        if data:
            branch_id, flyer_id, qty = data

            cur.execute("""
                UPDATE branch_flyer_stock
                SET remaining_quantity = remaining_quantity + %s
                WHERE branch_id = %s AND flyer_id = %s
            """, (qty, branch_id, flyer_id))

        cur.execute("DELETE FROM distributions WHERE id = %s", (record_id,))
        conn.commit()

    except Exception as e:
        conn.rollback()
        return f"Database error: {e}", 500

    finally:
        cur.close()
        conn.close()

    return redirect('/')


@app.route('/get_remaining')
def get_remaining():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = request.args.get('branch_id')
    flyer_id = request.args.get('flyer_id')

    if not branch_id or not flyer_id:
        return jsonify({"remaining": 0})

    cur.execute("""
        SELECT remaining_quantity
        FROM branch_flyer_stock
        WHERE branch_id = %s AND flyer_id = %s
    """, (int(branch_id), int(flyer_id)))

    row = cur.fetchone()

    cur.close()
    conn.close()

    remaining = row[0] if row else 0
    return jsonify({"remaining": remaining})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)