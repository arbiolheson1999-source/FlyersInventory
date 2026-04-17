from flask import Flask, render_template, request, redirect
import psycopg2
import os

app = Flask(__name__)

# 🔥 FIXED DATABASE CONNECTION FUNCTION
def get_conn():
    db_url = os.environ.get("postgresql://flyers_db_user:EPxxshJf2JINgzvYngYSiNgu74L9yV8Y@dpg-d79iv3qdbo4c73acmkpg-a/flyers_db")

    if not db_url:
        raise Exception("DATABASE_URL is not set")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(db_url)


# HOME PAGE
@app.route('/')
def index():
    conn = get_conn()
    cur = conn.cursor()

    # Get branches
    cur.execute("""
        SELECT b.id, b.name, COALESCE(SUM(s.remaining_quantity), 0) as total_remaining
        FROM branches b
        LEFT JOIN branch_flyer_stock s ON b.id = s.branch_id
        GROUP BY b.id, b.name
        ORDER BY b.name
    """)
    branches = cur.fetchall()

    # Get flyers
    cur.execute("SELECT id, name FROM flyers")
    flyers = cur.fetchall()

    # Get filters
    selected_branch = request.args.get('branch')
    selected_quarter = request.args.get('quarter')
    selected_month = request.args.get('month')
    selected_year = request.args.get('year')

    # Build summary query
    summary_query = """
        SELECT b.name, d.quarter, SUM(d.quantity) AS total_quantity
        FROM distributions d
        JOIN branches b ON d.branch_id = b.id
        WHERE 1=1
    """

    params = []

    if selected_branch:
        summary_query += " AND d.branch_id = %s"
        params.append(selected_branch)

    if selected_quarter:
        summary_query += " AND d.quarter = %s"
        params.append(selected_quarter)

    if selected_month:
        summary_query += " AND d.month = %s"
        params.append(selected_month)

    if selected_year:
        summary_query += " AND d.year = %s"
        params.append(selected_year)

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


# ADD STOCK
@app.route('/add_stock', methods=['POST'])
def add_stock():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = request.form['branch']
    flyer_id = request.form['flyer']
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
        return str(e), 500
    finally:
        cur.close()
        conn.close()

    return redirect('/')


# ADD DISTRIBUTION
@app.route('/add', methods=['POST'])
def add():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = request.form['branch']
    flyer_id = request.form['flyer']
    quantity = int(request.form['quantity'])
    month = int(request.form['month'])

    # Auto compute quarter
    if month in [1, 2, 3]:
        quarter = 'Q1'
    elif month in [4, 5, 6]:
        quarter = 'Q2'
    elif month in [7, 8, 9]:
        quarter = 'Q3'
    else:
        quarter = 'Q4'

    year = request.form['year']

    try:
        # Check stock
        cur.execute("""
            SELECT remaining_quantity 
            FROM branch_flyer_stock
            WHERE branch_id = %s AND flyer_id = %s
        """, (branch_id, flyer_id))

        row = cur.fetchone()

        if not row:
            conn.rollback()
            return "No stock for this branch", 400

        remaining = row[0]

        if quantity > remaining:
            conn.rollback()
            return f"Cannot distribute {quantity}, only {remaining} remaining", 400

        # Insert distribution
        cur.execute("""
            INSERT INTO distributions (branch_id, flyer_id, quantity, quarter, date)
            VALUES (%s, %s, %s, %s, MAKE_DATE(%s, %s, 1))
        """, (branch_id, flyer_id, quantity, quarter, year, month))

        # Deduct stock
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


# DELETE
@app.route('/delete', methods=['POST'])
def delete():
    conn = get_conn()
    cur = conn.cursor()

    record_id = request.form['record_id']

    try:
        cur.execute("SELECT flyer_id, quantity FROM distributions WHERE id = %s", (record_id,))
        data = cur.fetchone()

        if data:
            flyer_id, qty = data
            cur.execute("""
                UPDATE branch_flyer_stock
                SET remaining_quantity = remaining_quantity + %s
                WHERE flyer_id = %s
            """, (qty, flyer_id))

        cur.execute("DELETE FROM distributions WHERE id = %s", (record_id,))
        conn.commit()

    except Exception as e:
        conn.rollback()
        return f"Database error: {e}", 500
    finally:
        cur.close()
        conn.close()

    return redirect('/')


# GET REMAINING
@app.route('/get_remaining')
def get_remaining():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = request.args.get('branch_id')
    flyer_id = request.args.get('flyer_id')

    if not branch_id or not flyer_id:
        return {"remaining": 0}

    cur.execute("""
        SELECT remaining_quantity
        FROM branch_flyer_stock
        WHERE branch_id = %s AND flyer_id = %s
    """, (branch_id, flyer_id))

    row = cur.fetchone()

    cur.close()
    conn.close()

    remaining = row[0] if row else 0
    return {"remaining": remaining}


# RUN APP
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)