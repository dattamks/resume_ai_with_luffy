from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterView, LoginView, LogoutView, MeView, ChangePasswordView,
    NotificationPreferenceView, ForgotPasswordView, ResetPasswordView,
    WalletView, WalletTransactionListView, WalletTopUpView,
    PlanListView, PlanSubscribeView,
)
from .views_payments import (
    CreateSubscriptionView, VerifySubscriptionView, CancelSubscriptionView,
    SubscriptionStatusView, CreateTopUpOrderView, VerifyTopUpView,
    RazorpayWebhookView, PaymentHistoryView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('notifications/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    # Wallet & Credits
    path('wallet/', WalletView.as_view(), name='wallet'),
    path('wallet/transactions/', WalletTransactionListView.as_view(), name='wallet-transactions'),
    path('wallet/topup/', WalletTopUpView.as_view(), name='wallet-topup'),
    # Plans
    path('plans/', PlanListView.as_view(), name='plan-list'),
    path('plans/subscribe/', PlanSubscribeView.as_view(), name='plan-subscribe'),
    # Razorpay Payments
    path('payments/subscribe/', CreateSubscriptionView.as_view(), name='payment-subscribe'),
    path('payments/subscribe/verify/', VerifySubscriptionView.as_view(), name='payment-subscribe-verify'),
    path('payments/subscribe/cancel/', CancelSubscriptionView.as_view(), name='payment-subscribe-cancel'),
    path('payments/subscribe/status/', SubscriptionStatusView.as_view(), name='payment-subscribe-status'),
    path('payments/topup/', CreateTopUpOrderView.as_view(), name='payment-topup'),
    path('payments/topup/verify/', VerifyTopUpView.as_view(), name='payment-topup-verify'),
    path('payments/webhook/', RazorpayWebhookView.as_view(), name='payment-webhook'),
    path('payments/history/', PaymentHistoryView.as_view(), name='payment-history'),
]
