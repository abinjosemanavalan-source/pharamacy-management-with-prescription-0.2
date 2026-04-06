from flask import Blueprint, render_template, request, redirect, url_for, flash
from config import MYSQL_CONFIG
import mysql.connector

purchase_order_bp = Blueprint('purchase_order_bp', __name__)

def get_db():
    return mysql.connector.connect(**MYSQL_CONFIG)

@purchase_order_bp.route('/purchase_orders')
def view_purchase_orders():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT po.*, s.name as supplier_name 
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        ORDER BY po.order_date DESC
    """)
    purchase_orders = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('view_purchase_orders.html', purchase_orders=purchase_orders)

@purchase_order_bp.route('/create_purchase_order', methods=['GET', 'POST'])
def create_purchase_order():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        supplier_id = request.form['supplier_id']
        expected_delivery_date = request.form['expected_delivery_date']
        
        cursor.execute(
            "INSERT INTO purchase_orders (supplier_id, expected_delivery_date) VALUES (%s, %s)",
            (supplier_id, expected_delivery_date)
        )
        db.commit()
        po_id = cursor.lastrowid

        # Now add the items
        medicines = request.form.getlist('medicine_id[]')
        quantities = request.form.getlist('quantity[]')
        prices = request.form.getlist('price[]')

        for i in range(len(medicines)):
            cursor.execute(
                "INSERT INTO purchase_order_items (purchase_order_id, medicine_id, quantity, price) VALUES (%s, %s, %s, %s)",
                (po_id, medicines[i], quantities[i], prices[i])
            )
        
        db.commit()
        cursor.close()
        db.close()
        flash('Purchase Order created successfully!', 'success')
        return redirect(url_for('purchase_order_bp.view_purchase_orders'))

    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()
    cursor.execute("SELECT * FROM medicines")
    medicines = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('create_purchase_order.html', suppliers=suppliers, medicines=medicines)

@purchase_order_bp.route('/purchase_order/<int:id>')
def view_purchase_order_details(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT po.*, s.name as supplier_name 
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = %s
    """, (id,))
    purchase_order = cursor.fetchone()

    cursor.execute("""
        SELECT poi.*, m.name as medicine_name
        FROM purchase_order_items poi
        JOIN medicines m ON poi.medicine_id = m.id
        WHERE poi.purchase_order_id = %s
    """, (id,))
    items = cursor.fetchall()

    cursor.close()
    db.close()
    return render_template('view_purchase_order_details.html', purchase_order=purchase_order, items=items)

@purchase_order_bp.route('/receive_purchase_order/<int:id>')
def receive_purchase_order(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get the items from the purchase order
    cursor.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id = %s", (id,))
    items = cursor.fetchall()

    for item in items:
        # Get current stock before updating
        cursor.execute("SELECT stock FROM medicines WHERE id = %s", (item['medicine_id'],))
        med = cursor.fetchone()
        prev_stock = med['stock'] if med else 0
        new_stock  = prev_stock + item['quantity']

        cursor.execute(
            "UPDATE medicines SET stock = stock + %s WHERE id = %s",
            (item['quantity'], item['medicine_id'])
        )

        # Audit log
        try:
            cursor.execute(
                """INSERT INTO stock_movements
                   (medicine_id, user_id, previous_stock, new_stock, change_amount, movement_type)
                   VALUES (%s, %s, %s, %s, %s, 'purchase')""",
                (item['medicine_id'], 1, prev_stock, new_stock, item['quantity'])
            )
        except Exception:
            pass  # stock_movements table not created yet

    # Update the status of the purchase order
    cursor.execute("UPDATE purchase_orders SET status = 'received' WHERE id = %s", (id,))

    db.commit()
    cursor.close()
    db.close()

    flash('Purchase Order received and stock updated!', 'success')
    return redirect(url_for('purchase_order_bp.view_purchase_order_details', id=id))
