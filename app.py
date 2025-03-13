from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson.objectid import ObjectId
from datetime import datetime

# Flask App Initialization
app = Flask(__name__)
app.secret_key = "your_secret_key"

# MongoDB Configuration
app.config["MONGO_URI"] = "mongodb://localhost:27017/footwear_billing"
mongo = PyMongo(app)

# Extensions
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Collections
users_col = mongo.db.users
products_col = mongo.db.products
bills_col = mongo.db.bills
upi_payments_col = mongo.db.upi_payments
cash_payments_col = mongo.db.cash_payments

# User Class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if user:
        return User(str(user["_id"]), user["username"])
    return None

# Routes

@app.route("/")
@login_required
def home():
    products = list(products_col.find())
    return render_template("index.html", products=products)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = users_col.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            login_user(User(str(user["_id"]), user["username"]))
            return redirect(url_for("home"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))
@app.route("/product/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        size = request.form.get("size")
        price = float(request.form.get("price"))
        stock = int(request.form.get("stock"))

        if name and size and price and stock:
            existing_product = products_col.find_one({"name": name, "size": size})
            if existing_product:
                # Update stock if product exists
                products_col.update_one(
                    {"_id": existing_product["_id"]},
                    {"$inc": {"stock": stock}}
                )
                flash("Stock updated successfully!", "success")
            else:
                # Insert new product
                products_col.insert_one({
                    "name": name,
                    "description": description,
                    "size": size,
                    "price": price,
                    "stock": stock
                })
                flash("Product added successfully!", "success")
            return redirect(url_for("home"))
        else:
            flash("Please fill in all fields", "danger")
    return render_template("product_form.html", action_url=url_for("add_product"))

@app.route("/product/delete/<product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    try:
        product = products_col.find_one({"_id": ObjectId(product_id)})
        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for("home"))

        products_col.delete_one({"_id": ObjectId(product_id)})
        flash("Product deleted successfully!", "success")
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
    return redirect(url_for("home"))

@app.route("/bill", methods=["GET", "POST"])
@login_required
def generate_bill():
    if request.method == "POST":
        selected_products = request.json["products"]
        discount_percentage = request.json["discount"]  # Get discount percentage
        total_amount = 0

        bill_details = []
        for item in selected_products:
            product = products_col.find_one({"_id": ObjectId(item["product_id"])})

            if not product:
                continue

            quantity = int(item["quantity"])
            price = product["price"] * quantity
            total_amount += price

            bill_details.append({
                "product_id": str(product["_id"]),
                "name": product["name"],
                "quantity": quantity,
                "price": price,
            })

            # Deduct stock
            products_col.update_one({"_id": ObjectId(product["_id"])}, {"$inc": {"stock": -quantity}})

        # Calculate discount
        discount = (total_amount * discount_percentage) / 100
        final_amount = total_amount - discount

        bill_data = {
            "date": datetime.now(),
            "details": bill_details,
            "total_amount": total_amount,
            "discount_percentage": discount_percentage,
            "discount": discount,
            "final_amount": final_amount,
        }

        bill_id = bills_col.insert_one(bill_data).inserted_id

        bill_data["_id"] = str(bill_id)

        return jsonify({
            "status": "success",
            "message": "Bill generated successfully.",
            "bill_data": bill_data
        })

    products = list(products_col.find({"stock": {"$gt": 0}}))
    return render_template("generate_bill.html", products=products)

@app.route('/bill/pdf/<bill_id>')
@login_required
def print_bill(bill_id):
    bill_data = bills_col.find_one({"_id": ObjectId(bill_id)})
    if not bill_data:
        flash("Bill not found.", "danger")
        return redirect(url_for("home"))
    
    # Convert ObjectId to string for the template
    bill_data["_id"] = str(bill_data["_id"])
    return render_template("print_bill.html", bill_data=bill_data)

@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales_report():
    selected_date = None
    selected_month = None
    selected_year = None
    sales = []
    total_amount = 0

    if request.method == 'POST':
        # Get the selected date, month, and year from the form
        selected_date = request.form.get('date')
        selected_month = request.form.get('month')
        selected_year = request.form.get('year')

        # Create the query dictionary to filter sales
        query = {}

        if selected_date:
            # If a specific date is selected
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d')
            query["date"] = {"$gte": selected_date, "$lt": selected_date.replace(hour=23, minute=59, second=59, microsecond=999999)}

        elif selected_month:
            # If a specific month is selected
            selected_month = datetime.strptime(selected_month, '%Y-%m')
            query["date"] = {"$gte": selected_month, "$lt": selected_month.replace(hour=23, minute=59, second=59, microsecond=999999)}

        elif selected_year:
            # If a specific year is selected
            selected_year = int(selected_year)
            query["date"] = {"$gte": datetime(selected_year, 1, 1), "$lt": datetime(selected_year + 1, 1, 1)}

        # Query the sales data from MongoDB
        sales = list(bills_col.find(query))

        # Calculate the total sales amount for the filtered results
        total_amount = sum(sale["final_amount"] for sale in sales)

    return render_template(
        'sales.html',
        sales=sales,
        selected_date=selected_date,
        selected_month=selected_month,
        selected_year=selected_year,
        total_amount=total_amount
    )

@app.route("/stock")
@login_required
def stock():
    products = list(products_col.find())
    total_stock = sum(product["stock"] for product in products)
    return render_template("view_stock.html", products=products, total_stock=total_stock)

# UPI Payments Route
@app.route("/payments/upi", methods=["POST"])
@login_required
def view_upi_payments():
    upi_date = request.form.get("upi_date")
    upi_month = request.form.get("upi_month")
    upi_year = request.form.get("upi_year")

    # Filter payments based on user input
    payments = get_upi_payments(upi_date, upi_month, upi_year)  # Function to retrieve filtered payments
    total_upi = sum(payment["amount"] for payment in payments)

    return render_template("upi_payments_view.html", upi_payments=payments, upi_total=total_upi)

# Dummy function to simulate fetching UPI payments
def get_upi_payments(date=None, month=None, year=None):
    all_payments = [
        {"date": "2025-01-06", "amount": 1500.00},
        {"date": "2025-01-07", "amount": 2000.00},
        {"date": "2025-02-01", "amount": 1000.00}
    ]

    filtered_payments = []
    for payment in all_payments:
        payment_date = datetime.strptime(payment["date"], "%Y-%m-%d")

        if date and payment_date.date() == datetime.strptime(date, "%Y-%m-%d").date():
            filtered_payments.append(payment)
        elif month and payment_date.month == int(month.split("-")[1]):
            filtered_payments.append(payment)
        elif year and payment_date.year == int(year):
            filtered_payments.append(payment)

    return filtered_payments

# Cash Payments Route
@app.route("/payments/cash", methods=["POST"])
@login_required
def view_cash_payments():
    cash_date = request.form.get("cash_date")
    cash_month = request.form.get("cash_month")
    cash_year = request.form.get("cash_year")

    # Filter payments based on user input
    payments = get_cash_payments(cash_date, cash_month, cash_year)  # Function to retrieve filtered payments
    total_cash = sum(payment["amount"] for payment in payments)

    return render_template("cash_payments_view.html", cash_payments=payments, cash_total=total_cash)

# Dummy function to simulate fetching Cash payments
def get_cash_payments(date=None, month=None, year=None):
    all_cash_payments = [
        {"date": "2025-01-06", "amount": 1000.00},
        {"date": "2025-01-07", "amount": 1200.00},
        {"date": "2025-02-01", "amount": 500.00}
    ]

    filtered_payments = []
    for payment in all_cash_payments:
        payment_date = datetime.strptime(payment["date"], "%Y-%m-%d")

        if date and payment_date.date() == datetime.strptime(date, "%Y-%m-%d").date():
            filtered_payments.append(payment)
        elif month and payment_date.month == int(month.split("-")[1]):
            filtered_payments.append(payment)
        elif year and payment_date.year == int(year):
            filtered_payments.append(payment)

    return filtered_payments

# Run the App
if __name__ == "__main__":
    if not users_col.find_one({"username": "admin"}):
        users_col.insert_one({
            "username": "admin",
            "password": bcrypt.generate_password_hash("admin").decode("utf-8")
        })
    app.run(debug=True)
