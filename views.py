from django.shortcuts import render, redirect, get_object_or_404
from .models import Medicine, Cart, CartItem
from django.contrib.auth.decorators import login_required


@login_required
def add_to_cart(request, medicine_id):
    medicine = get_object_or_404(Medicine, id=medicine_id)

    cart, created = Cart.objects.get_or_create(user=request.user)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        medicine=medicine
    )

    if not created:
        cart_item.quantity += 1
        cart_item.save()

    return redirect('view_cart')


@login_required
def view_cart(request):
    cart = Cart.objects.filter(user=request.user).first()
    items = CartItem.objects.filter(cart=cart) if cart else []

    total = sum(item.total_price() for item in items)

    return render(request, 'cart.html', {
        'items': items,
        'total': total
    })