from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from supplier_routes import supplier_bp
from purchase_order_routes import purchase_order_bp
import mysql.connector
import os
import pytesseract
from PIL import Image
import cv2
import numpy as np
import traceback
from fuzzywuzzy import process
import re
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import MYSQL_CONFIG

# Path to tesseract (important in Windows)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Path that contains the 'tessdata' folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESSDATA_DIR = os.path.join(BASE_DIR, 'tessdata')
os.environ['TESSDATA_PREFIX'] = TESSDATA_DIR

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ===== MOCK KNOWLEDGE BASE FOR SMART ALERTS =====
MEDICINE_INFO = {
    "Rivobil": {"uses": "Treats anxiety and panic disorders.", "side_effects": "Drowsiness, dizziness", "warnings": "Avoid alcohol. May cause dependency."},
    "Ativan": {"uses": "Management of anxiety disorders.", "side_effects": "Drowsiness, weakness", "warnings": "Do not drive after taking."},
    "Sizodon Plus": {"uses": "Treats schizophrenia.", "side_effects": "Weight gain, sleepiness", "warnings": "Monitor blood sugar."},
    "Paracetamol": {"uses": "Pain relief, fever reduction.", "side_effects": "Rarely skin rash", "warnings": "Do not exceed 4g per day."},
    "Amoxicillin": {"uses": "Bacterial infections.", "side_effects": "Nausea, diarrhea", "warnings": "Complete the full course."},
    "Qutipin": {"uses": "Bipolar disorder, schizophrenia.", "side_effects": "Dry mouth, dizziness", "warnings": "May increase suicidal thoughts in young adults."},
    "Serta": {"uses": "Depression, OCD.", "side_effects": "Insomnia, nausea", "warnings": "Do not stop abruptly."}
}

app.register_blueprint(supplier_bp)
app.register_blueprint(purchase_order_bp)

# ===== GST CONFIGURATION =====
GST_PERCENTAGE = 12  # 12% GST on medicines (India standard)

def calculate_gst(subtotal):
    """Return GST breakdown dict for a given subtotal."""
    sub = round(float(subtotal), 2)
    gst = round(sub * (GST_PERCENTAGE / 100), 2)
    return {"subtotal": sub, "gst_percentage": GST_PERCENTAGE,
            "gst_amount": gst, "grand_total": round(sub + gst, 2)}

def log_stock_movement(cursor, medicine_id, user_id, prev_stock, new_stock, movement_type):
    """Write an audit entry to stock_movements. Silently skips if table not yet created."""
    try:
        cursor.execute(
            """INSERT INTO stock_movements
               (medicine_id, user_id, previous_stock, new_stock, change_amount, movement_type)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (medicine_id, user_id, prev_stock, new_stock, new_stock - prev_stock, movement_type)
        )
    except Exception:
        pass  # Table may not exist yet — run database/stock_movements.sql

# ========== FIXED ADMIN CREDENTIALS ==========
ADMIN_EMAIL = "admin@medicare.com"
ADMIN_PASSWORD = "admin123"
ADMIN_NAME = "Admin"
# ==============================================

def get_db():
    return mysql.connector.connect(**MYSQL_CONFIG)

def auto_create_admin():
    """Auto-create the admin account on startup if it doesn't exist."""
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE email=%s", (ADMIN_EMAIL,))
        existing = cursor.fetchone()
        if not existing:
            hashed_pw = generate_password_hash(ADMIN_PASSWORD)
            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, 'admin')",
                (ADMIN_NAME, ADMIN_EMAIL, hashed_pw)
            )
            db.commit()
            print(f"[SETUP] Admin account created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print(f"[SETUP] Admin account already exists: {ADMIN_EMAIL}")
        cursor.close()
        db.close()
    except Exception as e:
        print(f"[SETUP] Could not auto-create admin (DB may not be ready): {e}")

@app.context_processor
def inject_global_data():
    cart_count = 0
    user_data = None
    if 'user_id' in session:
        try:
            db = get_db()
            cursor = db.cursor(dictionary=True)
            
            # Fetch cart count
            cursor.execute("SELECT SUM(quantity) as total_qty FROM cart WHERE user_id=%s", (session['user_id'],))
            result = cursor.fetchone()
            if result and result['total_qty']:
                cart_count = result['total_qty']
                
            # Fetch user details
            cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
            user_data = cursor.fetchone()
            
            cursor.close()
            db.close()
        except:
            pass
    return dict(cart_count=cart_count, user=user_data)

# ---------- WELCOME ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/welcome')
def welcome():
    return render_template('welcome.html')

# ---------- REGISTER (Customer only — open to anyone) ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        # Block admin email from being registered publicly
        if email.lower() == ADMIN_EMAIL.lower():
            flash("This email is reserved. Please use a different email.", "danger")
            return redirect(url_for('login'))

        # Block staff emails from being registered publicly
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id FROM staff WHERE email=%s", (email,))
        is_staff = cursor.fetchone()
        if is_staff:
            flash("This email belongs to a staff member. Please contact admin for login credentials.", "danger")
            cursor.close()
            db.close()
            return redirect(url_for('login'))

        try:
            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, 'user')",
                (name, email, password)
            )
            db.commit()

            # Auto-login after registration
            cursor.execute("SELECT id, name, role FROM users WHERE email=%s", (email,))
            new_user = cursor.fetchone()
            if new_user:
                session['user_id'] = new_user['id']
                session['user'] = new_user['name']
                session['role'] = new_user['role']

            flash("Registration successful! Welcome to MediCare.", "success")
            return redirect(url_for('home'))
        except Exception as e:
            print(f"Registration error: {e}")
            flash("Email already exists!", "danger")
        finally:
            cursor.close()
            db.close()

    if request.method == 'GET':
        return redirect(url_for('login'))
    return redirect(url_for('login'))

# ---------- LOGIN ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        # Debug: print what's happening
        if not user:
            print(f"[LOGIN FAIL] No user found with email: {email}")
            # Check if they exist in staff table but not users table
            cursor.execute("SELECT * FROM staff WHERE email=%s", (email,))
            staff_exists = cursor.fetchone()
            if staff_exists:
                print(f"[LOGIN FAIL] Email '{email}' EXISTS in staff table but NOT in users table!")
                print(f"[LOGIN FAIL] This staff was added before auto-account creation. Re-add them via Admin → Add Staff.")
                flash("Your staff account needs to be re-created. Ask admin to delete and re-add you.", "warning")
            else:
                flash("Invalid email or password", "danger")
            cursor.close()
            db.close()
            return redirect(url_for('login'))

        if not check_password_hash(user['password'], password):
            print(f"[LOGIN FAIL] Wrong password for: {email} (role: {user['role']})")
            print(f"[LOGIN HINT] If this is a staff member, the default password is: staff123")
            flash("Invalid email or password", "danger")
            cursor.close()
            db.close()
            return redirect(url_for('login'))

        # Password is correct — now validate role
        if user['role'] == 'pharmacist':
            cursor.execute("SELECT id FROM staff WHERE email=%s", (email,))
            staff_record = cursor.fetchone()
            if not staff_record:
                print(f"[LOGIN FAIL] {email} has role 'pharmacist' but NOT in staff table. Access denied.")
                flash("Your staff access has been revoked. Contact admin.", "danger")
                cursor.close()
                db.close()
                return redirect(url_for('login'))

        # SUCCESS — set session
        session['user_id'] = user['id']
        session['role'] = user['role']
        session['user'] = user['name']
        session.permanent = True

        print(f"[LOGIN OK] {email} logged in as {user['role']}")

        # Show role-specific welcome message
        if user['role'] == 'admin':
            flash(f"Welcome back, Admin {user['name']}!", "success")
        elif user['role'] == 'pharmacist':
            flash(f"Welcome, Pharmacist {user['name']}!", "success")
        else:
            flash(f"Welcome, {user['name']}!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('home'))

    return render_template('login.html')


# ---------- HOME ----------
@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    context = {}
    if session.get('role') == 'admin':
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        context['orders_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM medicines")
        context['medicines_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role='user'")
        context['users_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM staff")
        context['staff_count'] = cursor.fetchone()['count']
    elif session.get('role') == 'pharmacist':
        # Pharmacist dashboard data
        cursor.execute("SELECT COUNT(*) as count FROM prescriptions WHERE status='pending'")
        context['pending_prescriptions'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM prescriptions WHERE status='approved'")
        context['approved_prescriptions'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        context['orders_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM medicines")
        context['medicines_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM medicines WHERE stock < 10")
        context['low_stock_count'] = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM medicines WHERE expiry_date <= CURDATE() + INTERVAL 30 DAY")
        context['expiry_alert_count'] = cursor.fetchone()['count']
        # Recent pending prescriptions for quick access
        cursor.execute("""
            SELECT p.id, u.name as patient_name, p.image_path, p.status, p.uploaded_at
            FROM prescriptions p
            JOIN users u ON p.user_id = u.id
            WHERE p.status = 'pending'
            ORDER BY p.uploaded_at DESC
            LIMIT 5
        """)
        context['recent_prescriptions'] = cursor.fetchall()
        # Recent orders for quick access
        cursor.execute("""
            SELECT o.id, u.name as customer_name, o.medicine_name, o.quantity, o.status, o.order_date
            FROM orders o
            JOIN users u ON o.user_id = u.id
            ORDER BY o.order_date DESC
            LIMIT 5
        """)
        context['recent_orders'] = cursor.fetchall()
    elif session.get('role') == 'user':
        search_query = request.args.get('q', '')
        if search_query:
            cursor.execute(
                "SELECT * FROM medicines WHERE name LIKE %s AND expiry_date > CURDATE() AND stock > 0",
                ("%" + search_query + "%",)
            )
        else:
            cursor.execute("SELECT * FROM medicines WHERE expiry_date > CURDATE() AND stock > 0 LIMIT 8")
        context['featured_medicines'] = cursor.fetchall()
        context['search_query'] = search_query

    cursor.close()
    db.close()
    
    return render_template('home.html', **context)

# ---------- MEDICINES ----------

@app.route('/medicines')
def medicines():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    search_query = request.args.get('q', '')
    is_user = (session.get('role') == 'user')
    expiry_filter = "AND expiry_date > CURDATE() AND stock > 0" if is_user else ""
    if search_query:
        cursor.execute(
            f"SELECT * FROM medicines WHERE name LIKE %s {expiry_filter}",
            ("%" + search_query + "%",)
        )
    else:
        cursor.execute(f"SELECT * FROM medicines WHERE 1=1 {expiry_filter}")
        
    medicines = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('medicines.html', medicines=medicines, search_query=search_query)


@app.route('/medicine/<int:id>')
def medicine_details(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM medicines WHERE id=%s", (id,))
    medicine = cursor.fetchone()
    cursor.close()
    db.close()
    
    if not medicine:
        flash("Medicine not found.", "danger")
        return redirect(url_for('medicines'))
        
    return render_template('medicine_details.html', medicine=medicine)

# ---------- PRESCRIPTION ----------

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == "POST":
        file = request.files.get("prescription")
        if file and file.filename:
            filename = secure_filename(file.filename)
            os.makedirs("static/uploads", exist_ok=True)
            file.save(os.path.join("static/uploads", filename))
            
            db = get_db()
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO prescriptions (user_id, image_path, status) VALUES (%s, %s, 'pending')",
                (session['user_id'], filename)
            )
            db.commit()
            cursor.close()
            db.close()
            
            flash("Prescription uploaded successfully!", "success")
            return redirect(url_for('history'))
        else:
            flash("Please attach a file.", "danger")
            
    return render_template("upload.html")

# ---------- HISTORY ----------
@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Fetch orders
    query_orders = """
        SELECT id, medicine_name, quantity, price, total, order_date, payment_method, status
        FROM orders
        WHERE user_id = %s
        ORDER BY order_date DESC
    """
    cursor.execute(query_orders, (session["user_id"],))
    orders = cursor.fetchall()

    # Fetch prescriptions
    query_prescriptions = """
        SELECT id, image_path, status, uploaded_at
        FROM prescriptions
        WHERE user_id = %s
        ORDER BY uploaded_at DESC
    """
    cursor.execute(query_prescriptions, (session["user_id"],))
    prescriptions = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template("history.html", orders=orders, prescriptions=prescriptions)

# ---------- TRACK ORDER ----------
@app.route('/track-order')
def track_order():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    order = None
    order_id = request.args.get('order_id')

    if order_id:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            """SELECT * FROM orders WHERE id=%s AND user_id=%s""",
            (order_id, session['user_id'])
        )
        order = cursor.fetchone()
        cursor.close()
        db.close()

        if not order:
            flash("Order not found. Please check your Order ID.", "danger")

    return render_template("tracking_order.html", order=order, order_id=order_id)

# ---------- CART ----------
@app.route('/add_to_cart/<int:medicine_id>')
def add_to_cart(medicine_id):
    if 'user_id' not in session:
        flash("Please login to add items to cart.", "warning")
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Check if item already exists in cart
    cursor.execute("SELECT * FROM cart WHERE user_id=%s AND medicine_id=%s", (user_id, medicine_id))
    item = cursor.fetchone()
    
    if item:
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE id=%s", (item['id'],))
    else:
        cursor.execute("INSERT INTO cart (user_id, medicine_id, quantity) VALUES (%s, %s, 1)", (user_id, medicine_id))
    
    db.commit()
    cursor.close()
    db.close()
    flash("Item added to cart!", "success")
    return redirect(url_for('medicines'))

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.id, m.name as medicine_name, m.price, c.quantity, (m.price * c.quantity) as total 
        FROM cart c 
        JOIN medicines m ON c.medicine_id = m.id 
        WHERE c.user_id = %s
    """, (user_id,))
    items = cursor.fetchall()
    
    grand_total = sum(item['total'] for item in items)
    
    cursor.close()
    db.close()

    return render_template('cart.html', items=items, grand_total=grand_total)

# ---------- PAY AND CHECKOUT ----------

@app.route('/checkout', methods=['GET'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.id, m.name as medicine_name, m.price, c.quantity, (m.price * c.quantity) as total 
        FROM cart c 
        JOIN medicines m ON c.medicine_id = m.id 
        WHERE c.user_id = %s
    """, (user_id,))
    items = cursor.fetchall()
    
    subtotal = sum(float(item['total']) for item in items) if items else 0
    grand_total = subtotal
    gst_data = calculate_gst(subtotal)

    cursor.close()
    db.close()

    return render_template('payment.html', items=items, grand_total=grand_total, gst_data=gst_data)

@app.route('/process_payment', methods=['POST'])
def process_payment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.id, m.name as medicine_name, m.price, c.quantity, (m.price * c.quantity) as total 
        FROM cart c 
        JOIN medicines m ON c.medicine_id = m.id 
        WHERE c.user_id = %s
    """, (user_id,))
    items = cursor.fetchall()
    
    order_ids = []
    for item in items:
        gst_info = calculate_gst(float(item['total']))
        gst_total = gst_info['grand_total']
        cursor.execute(
            "INSERT INTO orders (user_id, medicine_name, quantity, price, total, payment_method, status) VALUES (%s, %s, %s, %s, %s, 'Card', 'completed')",
            (user_id, item['medicine_name'], item['quantity'], item['price'], gst_total)
        )
        order_ids.append(str(cursor.lastrowid))
        cursor.execute(
            "INSERT INTO payments (user_id, amount, status) VALUES (%s, %s, 'completed')",
            (user_id, gst_total)
        )
        
    cursor.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()
    db.close()
    
    flash("Payment Successful! Your order has been placed.", "success")
    order_ids_str = ",".join(order_ids)
    return render_template('loading.html', order_ids=order_ids_str)

@app.route('/order_success')
def order_success():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    order_ids_str = request.args.get('ids', '')
    if not order_ids_str:
        return redirect(url_for('history'))
        
    ids = [int(i) for i in order_ids_str.split(',') if i.isdigit()]
    if not ids:
        return redirect(url_for('history'))
        
    format_strings = ','.join(['%s'] * len(ids))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT * FROM orders WHERE id IN ({format_strings}) AND user_id = %s", (*ids, session['user_id']))
    orders = cursor.fetchall()
    cursor.close()
    db.close()
    
    if not orders:
        return redirect(url_for('history'))
        
    return render_template('order_success.html', orders=orders, order_ids_str=order_ids_str)

# ---------- LOGOUT ----------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))



@app.route('/add_medicine', methods=['GET','POST'])
def add_medicine():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    if request.method == 'POST':

        name = request.form['name']
        company = request.form['company']
        price = request.form['price']
        stock = request.form['stock']
        supplier_id = request.form.get('supplier_id')
        category = request.form.get('category', 'General')
        expiry_date = request.form.get('expiry_date', '2030-01-01')
        description = request.form.get('description', '')
        
        photo = request.files.get('image')
        filename = secure_filename(photo.filename) if photo and photo.filename else None
        
        if filename:
            os.makedirs('static/uploads', exist_ok=True)
            photo.save(os.path.join('static/uploads', filename))

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "INSERT INTO medicines(name, company, price, stock, image_path, category, expiry_date, description, supplier_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (name, company, price, stock, filename, category, expiry_date, description, supplier_id)
        )
        new_med_id = cursor.lastrowid
        log_stock_movement(cursor, new_med_id, session.get('user_id'), 0, int(stock), 'adjustment')

        db.commit()

        cursor.close()
        db.close()

        return redirect('/medicines')

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('add_medicine.html', suppliers=suppliers)

@app.route('/view_medicines')
def view_medicines():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT m.*, s.name as supplier_name 
        FROM medicines m
        LEFT JOIN suppliers s ON m.supplier_id = s.id
    """)
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('view_medicines.html', medicines=data)


@app.route('/update_medicine/<int:id>', methods=['GET', 'POST'])
def update_medicine(id):
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        company = request.form['company']
        price = request.form['price']
        stock = request.form['stock']
        supplier_id = request.form.get('supplier_id')
        category = request.form.get('category', 'General')
        expiry_date = request.form.get('expiry_date', '2030-01-01')
        description = request.form.get('description', '')
        
        photo = request.files.get('image')
        filename = secure_filename(photo.filename) if photo and photo.filename else None

        if filename:
            os.makedirs('static/uploads', exist_ok=True)
            photo.save(os.path.join('static/uploads', filename))
            cursor.execute(
                "UPDATE medicines SET name=%s, company=%s, price=%s, stock=%s, image_path=%s, category=%s, expiry_date=%s, description=%s, supplier_id=%s WHERE id=%s",
                (name, company, price, stock, filename, category, expiry_date, description, supplier_id, id)
            )
        else:
            cursor.execute(
                "UPDATE medicines SET name=%s, company=%s, price=%s, stock=%s, category=%s, expiry_date=%s, description=%s, supplier_id=%s WHERE id=%s",
                (name, company, price, stock, category, expiry_date, description, supplier_id, id)
            )
        db.commit()
        cursor.close()
        db.close()
        return redirect('/view_medicines')

    cursor.execute("SELECT * FROM medicines WHERE id=%s", (id,))
    data = cursor.fetchone()
    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('update_medicine.html', medicine=data, suppliers=suppliers)


@app.route('/delete_medicine/<int:id>')
def delete_medicine(id):
    if session.get('role') != 'admin':
        flash("Only admins can delete medicines.", "danger")
        return redirect(url_for('view_medicines'))

    db = get_db()
    cursor = db.cursor()

    try:
        # Delete from cart first (items referencing this medicine)
        cursor.execute("DELETE FROM cart WHERE medicine_id=%s", (id,))
        
        # Delete from purchase_order_items (items referencing this medicine)
        cursor.execute("DELETE FROM purchase_order_items WHERE medicine_id=%s", (id,))
        
        # Now delete the medicine itself
        cursor.execute("DELETE FROM medicines WHERE id=%s", (id,))
        db.commit()
        
        flash("Medicine deleted successfully!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting medicine: {str(e)}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect('/view_medicines')



@app.route('/view_staff')
def view_staff():
    if session.get('role') != 'admin':
        flash("Only admins can manage staff.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM staff")
    data = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template('view_staff.html', staff=data)

@app.route('/update_staff/<int:id>', methods=['GET','POST'])
def update_staff(id):
    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        role = request.form.get('role')
        # We allow them to add/update details now in a generic text box mapping to address
        details = request.form.get('details', '')
        
        cursor.execute(
            "UPDATE staff SET name=%s,phone=%s,role=%s,address=%s WHERE id=%s",
            (name,phone,role,details,id)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect('/view_staff')

    cursor.execute("SELECT * FROM staff WHERE id=%s",(id,))
    data = cursor.fetchone()
    
    cursor.close()
    db.close()

    return render_template('update_staff.html', staff=data)

@app.route('/delete_staff_page')
def delete_staff_page():
    if session.get('role') != 'admin':
        flash("Only admins can manage staff.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM staff")
    data = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('delete_staff_page.html', staff=data)

@app.route('/delete_staff/<int:id>')
def delete_staff(id):
    if session.get('role') != 'admin':
        flash("Only admins can delete staff.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get the staff member's email to also delete their user account
    cursor.execute("SELECT email FROM staff WHERE id=%s", (id,))
    staff_row = cursor.fetchone()
    if staff_row and staff_row['email']:
        # Delete corresponding user account (pharmacist login)
        cursor.execute("DELETE FROM users WHERE email=%s AND role='pharmacist'", (staff_row['email'],))

    # Delete from staff table
    cursor.execute("DELETE FROM staff WHERE id=%s", (id,))
    db.commit()

    cursor.close()
    db.close()

    flash("Staff member deleted and their login access revoked.", "success")
    return redirect('/view_staff')


@app.route('/view_prescriptions')
def view_prescriptions():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT p.id, u.name, p.image_path, p.status 
        FROM prescriptions p 
        JOIN users u ON p.user_id = u.id
        ORDER BY p.id DESC
    """)
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('view_prescriptions.html', prescriptions=data)

@app.route('/view_orders')
def view_orders():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    status_filter = request.args.get('status', 'all')

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if status_filter and status_filter != 'all':
        cursor.execute("""
            SELECT o.*, u.name as customer_name 
            FROM orders o 
            JOIN users u ON o.user_id = u.id
            WHERE o.status = %s
            ORDER BY o.order_date DESC
        """, (status_filter,))
    else:
        cursor.execute("""
            SELECT o.*, u.name as customer_name 
            FROM orders o 
            JOIN users u ON o.user_id = u.id
            ORDER BY o.order_date DESC
        """)
    orders = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('view_orders.html', orders=orders, status_filter=status_filter)

@app.route('/update_order_status/<int:id>', methods=['POST'])
def update_order_status(id):
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    new_status = request.form.get('status')
    if new_status not in ['completed', 'processing', 'shipped', 'delivered', 'cancelled']:
        flash("Invalid status.", "danger")
        return redirect(url_for('view_orders'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, id))
    db.commit()
    cursor.close()
    db.close()

    flash(f"Order #{id} status updated to {new_status.title()}!", "success")
    return redirect(url_for('view_orders'))

@app.route('/verify_script', methods=['GET','POST'])
def verify_script():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        pid = request.form['prescription_id']
        status = request.form['status']

        cursor.execute(
            "UPDATE prescriptions SET status=%s WHERE id=%s",
            (status,pid)
        )
        db.commit()
        flash("Prescription status updated successfully!", "success")

    cursor.close()
    db.close()
    return redirect(url_for('view_prescriptions'))

# ========== HELPER FOR PRESCRIPTION PARSING ==========
def preprocess_for_ocr(img):
    """Advanced preprocessing for clearer OCR on messy handwritten prescriptions."""
    # 1. Scale up for better recognition of small text
    height, width = img.shape[:2]
    img = cv2.resize(img, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC)

    # 2. Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Noise removal (Median Blur is excellent for salt & pepper noise)
    denoised = cv2.medianBlur(gray, 3)

    # 4. Adaptive Thresholding (Much better than global Otsu for photos with uneven shadows/lighting)
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )

    # 5. Morphological Closing to connect disconnected faint ink strokes in handwriting
    kernel = np.ones((2, 2), np.uint8)
    processed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    return processed
def parse_prescription_entities(text, available_meds):
    """Use regex and fuzzy matching to extract structured data."""
    results = {
        "doctor": None,
        "patient": None,
        "diagnosis": None,
        "medicines": [],
        "text": text
    }
    
    lines = text.split('\n')
    
    # Regex patterns for common prescription headers
    dr_patterns = [r"Dr\.?\s*([A-Za-z\.\s]{3,})", r"DOCTOR:?\s*([A-Za-z\s]{3,})", r"Consultant\s*([A-Za-z\-]{3,})"]
    patient_patterns = [r"Mr\.?\s*([A-Za-z\s]{3,})", r"Ms\.?\s*([A-Za-z\s]{3,})", r"Mrs\.?\s*([A-Za-z\s]{3,})", r"Name:?\s*([A-Za-z\s]{3,})"]
    diag_patterns = [r"DIAGNOSIS:?\s*([A-Za-z\s]{3,})", r"Diagnosis:?\s*([A-Za-z\s]{3,})", r"IMPRESSION:?\s*([A-Za-z\s]{3,})", r"(Schizophrenia)", r"(Diabetes)", r"(Hypertension)"]
    dosage_patterns = r'(\d+\s*(tablet|tab|mg|ml|units|cap|capsule|spoon))|(\b(Morning|Night|BD|OD|TD|TDS|1-0-1|0-1-0|1-1-1|1-0-0|SOS)\b)'
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        
        # 1. Try to find Doctor
        if not results["doctor"]:
            for p in dr_patterns:
                match = re.search(p, line_clean, re.I)
                if match:
                    results["doctor"] = match.group(1).strip()
                    break
        
        # 2. Try to find Patient
        if not results["patient"]:
            for p in patient_patterns:
                match = re.search(p, line_clean, re.I)
                if match:
                    results["patient"] = match.group(1).strip()
                    break

        # 3. Try to find Diagnosis
        if not results["diagnosis"]:
            for p in diag_patterns:
                match = re.search(p, line_clean, re.I)
                if match:
                    if len(match.groups()) > 0 and match.group(1):
                        results["diagnosis"] = match.group(1).strip()
                    else:
                        results["diagnosis"] = match.group(0).strip()
                    break

        # 4. Fuzzy search medicines in this line
        words = line_clean.split()
        if len(words) > 0:
            # Check the whole line first
            matches = process.extract(line_clean, available_meds, limit=1)
            if matches and matches[0][1] > 75: # Slightly lower threshold for fuzzy match
                med_name = matches[0][0]
                if med_name not in [m["name"] for m in results["medicines"]]:
                    # Try to find dosage info on the same line
                    dosage_parts = []
                    for dosage_match in re.finditer(dosage_patterns, line_clean, re.I):
                        dosage_parts.append(dosage_match.group(0).strip())
                    
                    # Fetch smart info
                    info = next((v for k, v in MEDICINE_INFO.items() if k.lower() in med_name.lower() or med_name.lower() in k.lower()), None)

                    results["medicines"].append({
                        "name": med_name, 
                        "dosage": ", ".join(dosage_parts) if dosage_parts else None,
                        "raw": line_clean,
                        "info": info
                    })
            else:
                # Check individual words
                for word in words:
                    if len(word) < 4: continue
                    matches = process.extract(word, available_meds, limit=1)
                    # If it's a weak match, we can store a 'did_you_mean'
                    if matches and matches[0][1] > 85:
                        med_name = matches[0][0]
                        info = next((v for k, v in MEDICINE_INFO.items() if k.lower() in med_name.lower() or med_name.lower() in k.lower()), None)
                        if not any(m["name"] == med_name for m in results["medicines"]):
                            results["medicines"].append({
                                "name": med_name,
                                "dosage": None,
                                "raw": word,
                                "info": info
                            })
                    elif matches and 60 < matches[0][1] <= 85:
                        med_name = matches[0][0]
                        if not any(m["name"] == med_name for m in results["medicines"]):
                            results["medicines"].append({
                                "name": med_name,
                                "dosage": None,
                                "raw": word,
                                "did_you_mean": True
                            })

    return results

@app.route('/analyze_prescription/<int:id>')
def analyze_prescription(id):
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Only allow users to view their own prescriptions, admins/pharmacists can view any
    if session.get('role') in ['admin', 'pharmacist']:
        cursor.execute("SELECT image_path FROM prescriptions WHERE id=%s", (id,))
    else:
        cursor.execute("SELECT image_path FROM prescriptions WHERE id=%s AND user_id=%s", (id, session['user_id']))
        
    p = cursor.fetchone()
    
    if not p:
        cursor.close()
        db.close()
        return jsonify({"error": "Prescription not found"}), 404

    full_path = os.path.join("static/uploads", p['image_path'])
    
    try:
        # Read image
        img = cv2.imread(full_path)
        if img is None:
            img_pil = Image.open(full_path)
            # TESSDATA_PREFIX is set in env, so tesseract knows where to look
            text = pytesseract.image_to_string(img_pil)
        else:
            # Advanced preprocessing
            processed_img = preprocess_for_ocr(img)
            text = pytesseract.image_to_string(processed_img, config='--psm 6')
            
            if len(text.strip()) < 10:
                text = pytesseract.image_to_string(processed_img)

        # Get all medicines
        cursor.execute("SELECT name FROM medicines")
        meds_db = cursor.fetchall()
        cursor.close()
        db.close()
        
        medicine_names = [m['name'] for m in meds_db]
        # Add common ones
        common = ["Paracetamol", "Ibuprofen", "Amoxicillin", "Sizodon Plus", "Qutipin", "Ativan", "Rivobil", "Serta"]
        for c in common:
            if c not in medicine_names: medicine_names.append(c)

        # Parse
        parsed = parse_prescription_entities(text, medicine_names)
        
        # Compatibility with frontend (add found_medicines key)
        parsed["found_medicines"] = parsed["medicines"]
        
        return jsonify(parsed)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/download_prescription_pdf/<int:id>')
def download_prescription_pdf(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        import io
        from flask import send_file
        
        doctor = request.args.get('doctor', 'N/A')
        patient = request.args.get('patient', 'N/A')
        diagnosis = request.args.get('diagnosis', 'N/A')
        medicines = request.args.get('medicines', '')
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, "Medicare Pharmacy - AI Prescription Analysis")
        
        c.setFont("Helvetica", 12)
        c.drawString(50, 710, f"Patient Name: {patient}")
        c.drawString(50, 690, f"Doctor/Consultant: {doctor}")
        c.drawString(50, 670, f"Diagnosis: {diagnosis}")
        
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, 630, "Prescribed Medicines:")
        
        c.setFont("Helvetica", 12)
        y = 600
        for med in medicines.split('|'):
            if med:
                c.drawString(60, y, f"- {med}")
                y -= 25
                
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(50, 100, "This is an AI-generated report. Please verify with the original document.")
        c.showPage()
        c.save()
        
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f"Prescription_Report_{id}.pdf", mimetype='application/pdf')
    except Exception as e:
        flash(f"Error generating PDF", "danger")
        return redirect(request.referrer or url_for('home'))

@app.route('/view_payments')
def view_payments():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT p.id, u.name, p.amount, p.status 
        FROM payments p 
        JOIN users u ON p.user_id = u.id
    """)
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('view_payments.html', payments=data)

@app.route('/low_stock')
def low_stock():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name, stock FROM medicines WHERE stock < 10")
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('low_stock.html', medicines=data)

@app.route('/expiry_alert')
def expiry_alert():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT name, expiry_date FROM medicines WHERE expiry_date <= CURDATE() + INTERVAL 30 DAY"
    )
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('expiry_alert.html', medicines=data)
@app.route('/reorder_medicine', methods=['GET','POST'])
def reorder_medicine():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        medicine_name = request.form['medicine']
        quantity = int(request.form['quantity'])

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM medicines WHERE name LIKE %s", ("%" + medicine_name + "%",))
        meds = cursor.fetchall()
        med = meds[0] if meds else None
        
        if med:
            medicine_id = med['id']
            # Check if item already exists in cart
            cursor.execute("SELECT * FROM cart WHERE user_id=%s AND medicine_id=%s", (session['user_id'], medicine_id))
            item = cursor.fetchone()
            
            if item:
                cursor.execute("UPDATE cart SET quantity = quantity + %s WHERE id=%s", (quantity, item['id']))
            else:
                cursor.execute("INSERT INTO cart (user_id, medicine_id, quantity) VALUES (%s, %s, %s)", (session['user_id'], medicine_id, quantity))
            
            db.commit()
            flash(f"Added {quantity} x {med['name']} to cart!", "success")
            cursor.close()
            db.close()
            return redirect(url_for('cart'))
        else:
            flash("Medicine not found in inventory. Please check the name.", "danger")

        cursor.close()
        db.close()

    return render_template('reorder_medicine.html')


@app.route('/download_pdf')
def download_pdf():
    return render_template('download_pdf.html')


@app.route('/feedback', methods=['GET','POST'])
def feedback():
    if request.method == 'POST':
        message = request.form['message']

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "INSERT INTO feedback(message) VALUES(%s)", (message,)
        )

        db.commit()
        cursor.close()
        db.close()
        flash("Feedback sent to admin!", "success")
        return redirect(url_for('home'))

    return render_template('feedback.html')


@app.route('/rate_us', methods=['GET','POST'])
def rate_us():
    if request.method == 'POST':
        rating = request.form['rating']

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "INSERT INTO ratings(value) VALUES(%s)", (rating,)
        )

        db.commit()
        cursor.close()
        db.close()
        flash("Rating sent to admin!", "success")
        return redirect(url_for('home'))

    return render_template('rate_us.html')


@app.route('/file_complaint', methods=['GET','POST'])
def file_complaint():
    if request.method == 'POST':
        complaint = request.form['complaint']

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "INSERT INTO complaints(message) VALUES(%s)", (complaint,)
        )

        db.commit()
        cursor.close()
        db.close()
        flash("Complaint submitted to admin!", "success")
        return redirect(url_for('home'))

    return render_template('file_complaint.html')

@app.route('/view_reviews')
def view_reviews():
    if session.get('role') != 'admin':
        return redirect(url_for('home'))
        
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM feedback")
    feedbacks = cursor.fetchall()
    
    cursor.execute("SELECT * FROM complaints")
    complaints = cursor.fetchall()
    
    cursor.execute("SELECT * FROM ratings")
    ratings = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('view_reviews.html', feedbacks=feedbacks, complaints=complaints, ratings=ratings)


@app.route('/account')
def account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cursor.fetchone()
    
    # fetch prescription history for user
    cursor.execute("SELECT * FROM prescriptions WHERE user_id=%s ORDER BY id DESC LIMIT 5", (session['user_id'],))
    prescriptions = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('account.html', user=user, prescriptions=prescriptions)

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone_number')
        address = request.form.get('address')
        allergies = request.form.get('allergies')
        diseases = request.form.get('diseases')
        
        photo = request.files.get('profile_photo')
        filename = None
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            os.makedirs('static/uploads', exist_ok=True)
            photo.save(os.path.join('static/uploads', filename))
            
        if filename:
            cursor.execute("""
                UPDATE users SET name=%s, phone_number=%s, address=%s, allergies=%s, diseases=%s, profile_photo=%s WHERE id=%s
            """, (name, phone, address, allergies, diseases, filename, session['user_id']))
        else:
            cursor.execute("""
                UPDATE users SET name=%s, phone_number=%s, address=%s, allergies=%s, diseases=%s WHERE id=%s
            """, (name, phone, address, allergies, diseases, session['user_id']))
            
        db.commit()
        session['user'] = name
        flash("Profile updated successfully!", "success")
        return redirect(url_for('account'))
        
    cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    db.close()
    
    return render_template('edit_profile.html', user=user)


@app.route('/change_password', methods=['GET','POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash("New passwords do not match!", "danger")
            return redirect(url_for('change_password'))
            
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], current_password):
            hashed_pw = generate_password_hash(new_password)
            cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_pw, session['user_id']))
            db.commit()
            flash("Password changed successfully!", "success")
            cursor.close()
            db.close()
            return redirect(url_for('account'))
        else:
            flash("Incorrect current password", "danger")
            cursor.close()
            db.close()
            return redirect(url_for('change_password'))

    return render_template('change_password.html')




@app.route('/add_staff', methods=['GET','POST'])
def add_staff():
    if session.get('role') != 'admin':
        flash("Only admins can add staff.", "danger")
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        role = request.form['role']
        address = request.form['address']
        # Default password for new staff - they should change it on first login
        default_password = generate_password_hash('staff123')

        photo = request.files.get('photo')
        filename = ''
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            os.makedirs('static/staff_photos', exist_ok=True)
            photo.save(os.path.join('static/staff_photos', filename))

        db = get_db()
        cursor = db.cursor()

        try:
            # 1. Insert into staff table
            cursor.execute(
                "INSERT INTO staff(name, email, phone, role, address, photo) VALUES(%s,%s,%s,%s,%s,%s)",
                (name, email, phone, role, address, filename)
            )
            
            # 2. Create a user account so the staff member can LOG IN
            user_role = 'pharmacist' if role == 'pharmacist' else 'admin'
            cursor.execute(
                "INSERT INTO users(name, email, password, role) VALUES(%s,%s,%s,%s)",
                (name, email, default_password, user_role)
            )
            
            db.commit()
            flash(f"Staff member added successfully! Login: {email} / Password: staff123", "success")
        except Exception as e:
            db.rollback()
            print(f"Add staff error: {e}")
            if 'Duplicate entry' in str(e):
                flash("A staff member with this email already exists!", "danger")
            else:
                flash(f"Error adding staff: {str(e)}", "danger")
        finally:
            cursor.close()
            db.close()

        return redirect('/view_staff')

    return render_template('add_staff.html')


# ---------- LAB TESTS MODULE ----------
@app.route('/lab_tests')
def lab_tests():
    return render_template('lab_tests.html')

@app.route('/book_lab_test', methods=['GET', 'POST'])
def book_lab_test():
    if request.method == 'POST':
        flash('Test booked successfully! We will contact you soon.', 'success')
        return redirect(url_for('test_status'))
    return render_template('book_lab_test.html')

@app.route('/test_status')
def test_status():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('test_status.html')

@app.route('/download_test_report')
def download_test_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('download_test_report.html')

@app.route('/test_report')
def test_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('test_report.html')

@app.route('/chatbot_reply', methods=['POST'])
def chatbot_reply():
    data = request.get_json()
    msg = data.get('message', '').lower()
    
    reply = "I'm sorry, I didn't understand that. I can guide you on purchasing medicines, uploading your prescription, lab tests, and tracking orders!"
    
    if 'medicine' in msg or 'buy' in msg or 'order' in msg:
        reply = "To purchase medicines, browse our 'Medicines' page in the top menu, add items to your cart, and proceed to checkout!"
    elif 'prescription' in msg or 'upload' in msg or 'rx' in msg:
        reply = "To upload a prescription, navigate to 'More' -> 'Prescriptions'. After uploading it will be reviewed by our AI system and an expert pharmacist."
    elif 'lab' in msg or 'test' in msg or 'blood' in msg:
        reply = "Yes, we offer lab test bookings! Navigate to the 'Lab Tests' section from the top menu."
    elif 'track' in msg or 'where is my order' in msg or 'status' in msg:
        reply = "You can track your real-time order status by going to the 'Orders' page in your account menu."
    elif 'hello' in msg or 'hi' in msg or 'hey' in msg:
        reply = "Hello there! How can I guide you through MediCare?"
    elif 'contact' in msg or 'support' in msg or 'complaint' in msg or 'issue' in msg:
        reply = "If you need to contact admin, use the 'File a Complaint' or 'Feedback' links found in the website footer!"
        
    return jsonify({"reply": reply})

# ---------- SALES REPORT ----------
@app.route('/sales_report')
def sales_report():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT COALESCE(SUM(total), 0) as today_sales, COUNT(*) as today_orders
        FROM orders WHERE DATE(order_date) = CURDATE()
    """)
    today = cursor.fetchone()

    cursor.execute("""
        SELECT DATE_FORMAT(order_date, '%Y-%m') as month,
               SUM(total) as total_sales, COUNT(*) as order_count
        FROM orders
        GROUP BY DATE_FORMAT(order_date, '%Y-%m')
        ORDER BY month DESC LIMIT 12
    """)
    monthly = cursor.fetchall()

    cursor.execute("""
        SELECT medicine_name, SUM(quantity) as total_qty, SUM(total) as revenue
        FROM orders
        GROUP BY medicine_name
        ORDER BY total_qty DESC LIMIT 5
    """)
    top_medicines = cursor.fetchall()

    cursor.execute("SELECT COALESCE(SUM(total),0) as grand_total, COUNT(*) as total_orders FROM orders")
    overall = cursor.fetchone()

    cursor.execute("""
        SELECT DATE_FORMAT(order_date, '%Y-%m-%d') as day, SUM(total) as daily_sales
        FROM orders WHERE order_date >= CURDATE() - INTERVAL 7 DAY
        GROUP BY DATE_FORMAT(order_date, '%Y-%m-%d')
        ORDER BY day ASC
    """)
    weekly = cursor.fetchall()

    cursor.close()
    db.close()
    return render_template('sales_report.html',
                           today=today, monthly=monthly,
                           top_medicines=top_medicines,
                           overall=overall, weekly=weekly)

# ---------- INVOICE GENERATION ----------
@app.route('/generate_invoice/<order_ids>')
def generate_invoice(order_ids):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    ids = [int(i) for i in order_ids.split(',') if i.isdigit()]
    if not ids:
        return redirect(url_for('history'))

    format_strings = ','.join(['%s'] * len(ids))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    if session.get('role') in ['admin', 'pharmacist']:
        cursor.execute(f"""
            SELECT o.*, u.name as customer_name, u.email as customer_email, u.phone_number
            FROM orders o JOIN users u ON o.user_id = u.id WHERE o.id IN ({format_strings})
        """, tuple(ids))
    else:
        cursor.execute(f"""
            SELECT o.*, u.name as customer_name, u.email as customer_email, u.phone_number
            FROM orders o JOIN users u ON o.user_id = u.id WHERE o.id IN ({format_strings}) AND o.user_id = %s
        """, (*ids, session['user_id']))
    orders = cursor.fetchall()
    cursor.close()
    db.close()

    if not orders:
        flash("Order not found.", "danger")
        return redirect(url_for('history'))
        
    order = orders[0]

    try:
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        import io
        from flask import send_file

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=1.5*cm, bottomMargin=1.5*cm,
                                leftMargin=2*cm, rightMargin=2*cm)
        styles = getSampleStyleSheet()
        blue = rl_colors.HexColor('#2563eb')
        elements = []

        center = ParagraphStyle('center', parent=styles['Normal'], alignment=TA_CENTER)
        right  = ParagraphStyle('right',  parent=styles['Normal'], alignment=TA_RIGHT)

        # ---- Header ----
        elements.append(Paragraph("<b><font size=18 color='#2563eb'>MediCare Pharmacy</font></b>", center))
        elements.append(Paragraph("124 Health Avenue, Medical District | Tel: +1(800)123-4567 | support@medicare.com", center))
        elements.append(Spacer(1, 0.4*cm))
        
        invoice_title = f"<b>TAX INVOICE — #{order['id']}</b>" if len(ids) == 1 else "<b>TAX INVOICE — Combined</b>"
        elements.append(Paragraph(invoice_title, center))
        elements.append(Spacer(1, 0.5*cm))

        # ---- Customer info ----
        info_data = [
            ["Customer:", order['customer_name'],  "Date:", str(order['order_date'])[:16]],
            ["Email:",    order['customer_email'], "Status:",     order.get('status','').title()],
            ["Phone:",    order.get('phone_number','N/A'), "Payment:", order.get('payment_method','Card')],
        ]
        info_t = Table(info_data, colWidths=[3*cm, 7*cm, 3.5*cm, 4*cm])
        info_t.setStyle(TableStyle([
            ('FONTNAME',  (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME',  (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTSIZE',  (0,0), (-1,-1), 9),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(info_t)
        elements.append(Spacer(1, 0.5*cm))

        # ---- Items table ----
        tbl_data = [['Medicine', 'Qty', 'Unit Price', 'Amount']]
        
        total_subtotal = 0
        for current_order in orders:
            sub = float(current_order['price']) * int(current_order['quantity'])
            total_subtotal += sub
            tbl_data.append([
                current_order['medicine_name'], 
                str(current_order['quantity']),
                f"Rs.{float(current_order['price']):.2f}", 
                f"Rs.{sub:.2f}"
            ])
            
        gst_d = calculate_gst(total_subtotal)

        tbl_data.append(['', '', 'Subtotal:', f"Rs.{gst_d['subtotal']:.2f}"])
        tbl_data.append(['', '', f"GST ({GST_PERCENTAGE}%):", f"Rs.{gst_d['gst_amount']:.2f}"])
        tbl_data.append(['', '', 'GRAND TOTAL:', f"Rs.{gst_d['grand_total']:.2f}"])
        
        col_w = [9*cm, 2*cm, 4.5*cm, 3*cm]
        tbl = Table(tbl_data, colWidths=col_w)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), blue),
            ('TEXTCOLOR',     (0,0), (-1,0), rl_colors.white),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME',      (2,2), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 10),
            ('ROWBACKGROUNDS',(0,1), (-1,-3), [rl_colors.white, rl_colors.HexColor('#f0f4ff')]),
            ('BACKGROUND',    (0,-1), (-1,-1), rl_colors.HexColor('#dbeafe')),
            ('LINEABOVE',     (0,-1), (-1,-1), 1.5, blue),
            ('GRID',          (0,0), (-1,0), 0.5, rl_colors.white),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        elements.append(tbl)
        elements.append(Spacer(1, 0.8*cm))
        elements.append(Paragraph(
            "<i>This is a system-generated invoice. Thank you for choosing MediCare Pharmacy.</i>",
            center))

        doc.build(elements)
        buffer.seek(0)
        
        filename_id = order['id'] if len(ids) == 1 else f"combo_{ids[0]}_to_{ids[-1]}"
        return send_file(buffer, as_attachment=True,
                         download_name=f"MediCare_Invoice_{filename_id}.pdf",
                         mimetype='application/pdf')
    except Exception as e:
        flash(f"Invoice error: {str(e)}", "danger")
        return redirect(url_for('history'))

# ---------- STOCK MOVEMENT LOG ----------
@app.route('/stock_movements')
def view_stock_movements():
    if session.get('role') not in ['admin', 'pharmacist']:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT sm.*, m.name as medicine_name, u.name as user_name
            FROM stock_movements sm
            JOIN medicines m ON sm.medicine_id = m.id
            JOIN users u ON sm.user_id = u.id
            ORDER BY sm.created_at DESC LIMIT 100
        """)
        movements = cursor.fetchall()
    except Exception:
        movements = []
        flash("Stock movement log not set up. Run: database/stock_movements.sql in phpMyAdmin.", "warning")
    cursor.close()
    db.close()
    return render_template('stock_movements.html', movements=movements)

 # ⚠️ THIS MUST BE LAST
if __name__ == '__main__':
    auto_create_admin()  # Create admin account if it doesn't exist
    app.run(debug=True, host='0.0.0.0', port=5000)
