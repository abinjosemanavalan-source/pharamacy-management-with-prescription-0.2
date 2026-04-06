from flask import Blueprint, render_template, request, redirect, url_for, flash
from config import MYSQL_CONFIG
import mysql.connector

supplier_bp = Blueprint('supplier_bp', __name__)

def get_db():
    return mysql.connector.connect(**MYSQL_CONFIG)

@supplier_bp.route('/suppliers')
def view_suppliers():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('view_suppliers.html', suppliers=suppliers)

@supplier_bp.route('/add_supplier', methods=['GET', 'POST'])
def add_supplier():
    if request.method == 'POST':
        name = request.form['name']
        contact_person = request.form['contact_person']
        email = request.form['email']
        phone = request.form['phone']
        address = request.form['address']

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO suppliers (name, contact_person, email, phone, address) VALUES (%s, %s, %s, %s, %s)",
            (name, contact_person, email, phone, address)
        )
        db.commit()
        cursor.close()
        db.close()
        flash('Supplier added successfully!', 'success')
        return redirect(url_for('supplier_bp.view_suppliers'))
    return render_template('add_supplier.html')

@supplier_bp.route('/update_supplier/<int:id>', methods=['GET', 'POST'])
def update_supplier(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        contact_person = request.form['contact_person']
        email = request.form['email']
        phone = request.form['phone']
        address = request.form['address']
        
        cursor.execute(
            "UPDATE suppliers SET name=%s, contact_person=%s, email=%s, phone=%s, address=%s WHERE id=%s",
            (name, contact_person, email, phone, address, id)
        )
        db.commit()
        cursor.close()
        db.close()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('supplier_bp.view_suppliers'))

    cursor.execute("SELECT * FROM suppliers WHERE id=%s", (id,))
    supplier = cursor.fetchone()
    cursor.close()
    db.close()
    return render_template('update_supplier.html', supplier=supplier)

@supplier_bp.route('/delete_supplier/<int:id>')
def delete_supplier(id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM suppliers WHERE id=%s", (id,))
    db.commit()
    cursor.close()
    db.close()
    flash('Supplier deleted successfully!', 'success')
    return redirect(url_for('supplier_bp.view_suppliers'))
