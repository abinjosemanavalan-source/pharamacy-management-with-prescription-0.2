from django.urls import path
from . import views

app_name = 'pharmacy'

urlpatterns = [


    path('', views.login, name='login'),
    path('login/', views.login_post, name='login_post'),
    path('logout/', views.logout, name='logout'),
    path('change-password/', views.change_password, name='change_password'),
    path('change-password/submit/', views.change_password_post, name='change_password_post'),

    path('dashboard/admin/', views.admin_home, name='admin_home'),
    path('dashboard/staff/', views.staff_home, name='staff_home'),
    path('dashboard/user/', views.user_home, name='user_home'),

    path('users/', views.view_users, name='view_users'),
    path('users/<int:id>/verify/', views.verify_user, name='verify_user'),
    path('users/<int:id>/reject/', views.reject_user, name='reject_user'),

    path('medicines/', views.view_medicine, name='view_medicine'),
    path('medicines/add/', views.add_medicine, name='add_medicine'),
    path('medicines/add/submit/', views.add_medicine_post, name='add_medicine_post'),
    path('medicines/<int:id>/edit/', views.edit_medicine, name='edit_medicine'),
    path('medicines/<int:id>/edit/submit/', views.edit_medicine_post, name='edit_medicine_post'),
    path('medicines/<int:id>/delete/', views.delete_medicine, name='delete_medicine'),

    path('stock/', views.view_stock, name='view_stock'),
    path('stock/<int:id>/add/', views.add_stock, name='add_stock'),
    path('stock/<int:id>/add/submit/', views.add_stock_post, name='add_stock_post'),

    path('prescriptions/', views.view_prescriptions, name='view_prescriptions'),
    path('prescriptions/upload/', views.upload_prescription, name='upload_prescription'),
    path('prescriptions/upload/submit/', views.upload_prescription_post, name='upload_prescription_post'),
    path('prescriptions/<int:id>/verify/', views.verify_prescription, name='verify_prescription'),
    path('prescriptions/<int:id>/reject/', views.reject_prescription, name='reject_prescription'),
    path('prescriptions/<int:id>/scan/', views.scan_prescription, name='scan_prescription'),  # AI/OCR

    path('cart/', views.view_cart, name='view_cart'),
    path('cart/add/<int:id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:id>/', views.remove_cart, name='remove_cart'),
    path('checkout/', views.checkout, name='checkout'),


    path('payment/', views.payment, name='payment'),
    path('payment/submit/', views.payment_post, name='payment_post'),

   
    path('orders/', views.view_orders, name='view_orders'),
    path('orders/<int:id>/approve/', views.approve_order, name='approve_order'),
    path('orders/<int:id>/reject/', views.reject_order, name='reject_order'),
    path('orders/history/', views.order_history, name='order_history'),

    path('staff/', views.view_staff, name='view_staff'),
    path('staff/add/', views.add_staff, name='add_staff'),
    path('staff/add/submit/', views.add_staff_post, name='add_staff_post'),
    path('staff/<int:id>/delete/', views.delete_staff, name='delete_staff'),

   
    path('reports/sales/', views.view_sales, name='view_sales'),
    path('reports/daily/', views.daily_report, name='daily_report'),


    path('complaints/', views.view_complaints, name='view_complaints'),
    path('complaints/send/', views.send_complaint, name='send_complaint'),
    path('complaints/send/submit/', views.send_complaint_post, name='send_complaint_post'),
    path('complaints/<int:id>/reply/', views.reply_complaint, name='reply_complaint'),
    path('complaints/<int:id>/reply/submit/', views.reply_complaint_post, name='reply_complaint_post'),

   
    path('feedback/', views.feedback, name='feedback'),
    path('feedback/submit/', views.feedback_post, name='feedback_post'),
    path('feedback/all/', views.view_feedback, name='view_feedback'),

]