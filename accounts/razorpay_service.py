"""
Razorpay payment gateway integration service.

Handles:
- Subscription creation & management (Pro plan auto-renewal)
- One-time order creation (credit top-up packs)
- Payment verification (signature-based)
- Webhook event processing
- Idempotent credit/plan provisioning

All Razorpay API calls and payment state transitions go through this module.
"""
import hashlib
import hmac
import logging
import time

import razorpay
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('accounts')


def _get_client() -> razorpay.Client:
    """Lazy Razorpay client. Raises if keys are placeholder/missing."""
    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
    if 'placeholder' in key_id or 'placeholder' in key_secret:
        logger.warning('Razorpay keys are placeholders — API calls will fail.')
    return razorpay.Client(auth=(key_id, key_secret))


# ── Subscription Flow (Pro Plan) ────────────────────────────────────────────

def create_subscription(user, plan_slug: str) -> dict:
    """
    Create a Razorpay subscription for a plan.

    1. Validates the plan exists and has a razorpay_plan_id in notes.
    2. Calls Razorpay Subscriptions API.
    3. Stores a local RazorpaySubscription + RazorpayPayment record.
    4. Returns subscription details for frontend checkout.

    The plan must have a corresponding Razorpay Plan created in the
    Razorpay Dashboard. The Razorpay plan_id is stored in Plan.description
    or configured via settings. For now, we derive it from the plan slug.
    """
    from .models import Plan, RazorpayPayment, RazorpaySubscription

    try:
        plan = Plan.objects.get(slug=plan_slug, is_active=True)
    except Plan.DoesNotExist:
        raise ValueError(f'Plan "{plan_slug}" not found or inactive.')

    if plan.price == 0:
        raise ValueError('Cannot create a subscription for a free plan.')

    # Check if user already has an active subscription
    existing = RazorpaySubscription.objects.filter(
        user=user,
        status__in=[
            RazorpaySubscription.STATUS_CREATED,
            RazorpaySubscription.STATUS_AUTHENTICATED,
            RazorpaySubscription.STATUS_ACTIVE,
            RazorpaySubscription.STATUS_PENDING,
        ],
    ).first()
    if existing:
        raise ValueError(
            f'You already have an active subscription (ID: {existing.razorpay_subscription_id}). '
            'Cancel it first before creating a new one.'
        )

    # Razorpay plan_id mapping — in production, store this in the Plan model
    # or a separate config. For now, use a convention: plan_{slug}_monthly
    razorpay_plan_id = _get_razorpay_plan_id(plan)

    client = _get_client()

    amount_paise = int(plan.price * 100)

    try:
        rz_subscription = client.subscription.create({
            'plan_id': razorpay_plan_id,
            'total_count': 12,  # Max 12 billing cycles (1 year), auto-renews
            'quantity': 1,
            'notes': {
                'user_id': str(user.id),
                'username': user.username,
                'plan_slug': plan.slug,
            },
        })
    except Exception as e:
        logger.error('Razorpay subscription creation failed: user=%s plan=%s error=%s',
                     user.username, plan_slug, str(e))
        raise ValueError(f'Payment gateway error: {str(e)}')

    # Store local subscription record
    subscription = RazorpaySubscription.objects.create(
        user=user,
        plan=plan,
        razorpay_subscription_id=rz_subscription['id'],
        razorpay_plan_id=razorpay_plan_id,
        status=RazorpaySubscription.STATUS_CREATED,
        short_url=rz_subscription.get('short_url', ''),
    )

    # Create a payment record for tracking
    RazorpayPayment.objects.create(
        user=user,
        payment_type=RazorpayPayment.PAYMENT_TYPE_SUBSCRIPTION,
        razorpay_subscription_id=rz_subscription['id'],
        amount=amount_paise,
        currency=settings.RAZORPAY_CURRENCY,
        status=RazorpayPayment.STATUS_CREATED,
        notes={'plan_slug': plan.slug, 'subscription_id': rz_subscription['id']},
    )

    logger.info(
        'Subscription created: user=%s plan=%s rz_sub_id=%s',
        user.username, plan_slug, rz_subscription['id'],
    )

    return {
        'subscription_id': rz_subscription['id'],
        'razorpay_plan_id': razorpay_plan_id,
        'short_url': rz_subscription.get('short_url', ''),
        'status': rz_subscription.get('status', 'created'),
        'key_id': settings.RAZORPAY_KEY_ID,
        'plan_name': plan.name,
        'amount': amount_paise,
        'currency': settings.RAZORPAY_CURRENCY,
    }


def verify_subscription_payment(
    user,
    razorpay_subscription_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Verify a subscription payment after Razorpay checkout completes.

    1. Verify signature using HMAC-SHA256.
    2. Update RazorpayPayment record.
    3. Activate subscription + upgrade user's plan.
    4. Grant bonus credits.

    Returns result dict.
    """
    from .models import RazorpayPayment, RazorpaySubscription

    # Signature verification
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f'{razorpay_payment_id}|{razorpay_subscription_id}'.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, razorpay_signature):
        logger.warning(
            'Subscription payment signature mismatch: user=%s sub_id=%s',
            user.username, razorpay_subscription_id,
        )
        raise ValueError('Payment verification failed: invalid signature.')

    return _activate_subscription(user, razorpay_subscription_id, razorpay_payment_id, razorpay_signature)


@transaction.atomic
def _activate_subscription(
    user,
    razorpay_subscription_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str = '',
    via_webhook: bool = False,
) -> dict:
    """
    Internal: activate subscription and provision credits.
    Idempotent — skips if already provisioned for this payment_id.
    """
    from .models import RazorpayPayment, RazorpaySubscription
    from .services import subscribe_plan

    # Idempotency: check if we already processed this payment
    existing_payment = RazorpayPayment.objects.filter(
        razorpay_payment_id=razorpay_payment_id,
        credits_granted=True,
    ).first()
    if existing_payment:
        logger.info('Payment already processed (idempotent skip): payment_id=%s', razorpay_payment_id)
        return {
            'status': 'already_processed',
            'message': 'This payment has already been processed.',
            'payment_id': razorpay_payment_id,
        }

    # Update payment record
    payment = RazorpayPayment.objects.filter(
        razorpay_subscription_id=razorpay_subscription_id,
        status=RazorpayPayment.STATUS_CREATED,
    ).first()

    if payment:
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.status = RazorpayPayment.STATUS_CAPTURED
        payment.webhook_verified = via_webhook
        payment.credits_granted = True
        payment.save()
    else:
        # Payment record doesn't exist (e.g., webhook came before frontend verify)
        # Find subscription to get amount info
        sub = RazorpaySubscription.objects.filter(
            razorpay_subscription_id=razorpay_subscription_id,
        ).first()
        amount = int(sub.plan.price * 100) if sub else 0

        payment = RazorpayPayment.objects.create(
            user=user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_SUBSCRIPTION,
            razorpay_subscription_id=razorpay_subscription_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            amount=amount,
            currency=settings.RAZORPAY_CURRENCY,
            status=RazorpayPayment.STATUS_CAPTURED,
            webhook_verified=via_webhook,
            credits_granted=True,
            notes={'source': 'webhook' if via_webhook else 'frontend_verify'},
        )

    # Update subscription status
    try:
        subscription = RazorpaySubscription.objects.select_for_update().get(
            razorpay_subscription_id=razorpay_subscription_id,
        )
        subscription.status = RazorpaySubscription.STATUS_ACTIVE
        subscription.current_start = timezone.now()
        subscription.current_end = timezone.now() + timezone.timedelta(days=30)
        subscription.save()

        # Upgrade user's plan
        plan_slug = subscription.plan.slug
        result = subscribe_plan(user, plan_slug)

        logger.info(
            'Subscription activated: user=%s sub_id=%s payment_id=%s plan=%s via=%s',
            user.username, razorpay_subscription_id, razorpay_payment_id,
            plan_slug, 'webhook' if via_webhook else 'frontend',
        )

        return {
            'status': 'activated',
            'message': f'Subscription activated. {result.get("message", "")}',
            'plan': plan_slug,
            'payment_id': razorpay_payment_id,
            'subscription_id': razorpay_subscription_id,
        }
    except RazorpaySubscription.DoesNotExist:
        logger.error('Subscription not found during activation: sub_id=%s', razorpay_subscription_id)
        raise ValueError('Subscription record not found.')


def cancel_subscription(user) -> dict:
    """
    Cancel the user's active Razorpay subscription.

    - Calls Razorpay API to cancel at end of current billing cycle.
    - Updates local subscription status.
    - Schedules plan downgrade (user keeps Pro until cycle ends).
    """
    from .models import RazorpaySubscription
    from .services import subscribe_plan

    try:
        subscription = RazorpaySubscription.objects.get(
            user=user,
            status__in=[
                RazorpaySubscription.STATUS_ACTIVE,
                RazorpaySubscription.STATUS_AUTHENTICATED,
                RazorpaySubscription.STATUS_PENDING,
            ],
        )
    except RazorpaySubscription.DoesNotExist:
        raise ValueError('No active subscription found.')

    client = _get_client()

    try:
        client.subscription.cancel(subscription.razorpay_subscription_id, {
            'cancel_at_cycle_end': 1,  # Don't cancel immediately
        })
    except Exception as e:
        logger.error(
            'Razorpay subscription cancel failed: user=%s sub_id=%s error=%s',
            user.username, subscription.razorpay_subscription_id, str(e),
        )
        raise ValueError(f'Failed to cancel subscription: {str(e)}')

    subscription.status = RazorpaySubscription.STATUS_CANCELLED
    subscription.save(update_fields=['status', 'updated_at'])

    # Schedule downgrade to free plan
    result = subscribe_plan(user, 'free')

    logger.info(
        'Subscription cancelled: user=%s sub_id=%s',
        user.username, subscription.razorpay_subscription_id,
    )

    return {
        'status': 'cancelled',
        'message': 'Subscription cancelled. You will retain Pro access until the end of the billing cycle.',
        'effective_date': subscription.current_end.isoformat() if subscription.current_end else None,
        'downgrade_info': result,
    }


def get_subscription_status(user) -> dict:
    """Get the current subscription status for a user."""
    from .models import RazorpaySubscription

    try:
        subscription = RazorpaySubscription.objects.select_related('plan').get(user=user)
        return {
            'has_subscription': True,
            'subscription_id': subscription.razorpay_subscription_id,
            'plan': subscription.plan.slug,
            'plan_name': subscription.plan.name,
            'status': subscription.status,
            'is_active': subscription.is_active,
            'current_start': subscription.current_start,
            'current_end': subscription.current_end,
            'created_at': subscription.created_at,
        }
    except RazorpaySubscription.DoesNotExist:
        return {
            'has_subscription': False,
            'status': None,
            'is_active': False,
        }


# ── Top-Up Flow (One-Time Orders) ───────────────────────────────────────────

def create_topup_order(user, quantity: int = 1) -> dict:
    """
    Create a Razorpay order for a one-time credit top-up.

    1. Validates user's plan supports top-ups.
    2. Creates Razorpay order via Orders API.
    3. Stores a local RazorpayPayment record.
    4. Returns order details for frontend checkout.
    """
    from .models import RazorpayPayment

    profile = user.profile
    plan = profile.plan

    if not plan or plan.topup_credits_per_pack == 0:
        raise ValueError('Your plan does not support credit top-ups.')

    if profile.pending_plan is not None:
        raise ValueError('Cannot top up while a plan downgrade is pending.')

    if quantity < 1:
        raise ValueError('Quantity must be at least 1.')

    total_price = plan.topup_price * quantity
    amount_paise = int(total_price * 100)
    credits_to_add = plan.topup_credits_per_pack * quantity

    client = _get_client()

    try:
        rz_order = client.order.create({
            'amount': amount_paise,
            'currency': settings.RAZORPAY_CURRENCY,
            'receipt': f'topup_{user.id}_{int(time.time())}',
            'notes': {
                'user_id': str(user.id),
                'username': user.username,
                'type': 'topup',
                'quantity': str(quantity),
                'credits': str(credits_to_add),
                'plan_slug': plan.slug,
            },
        })
    except Exception as e:
        logger.error(
            'Razorpay order creation failed: user=%s quantity=%d error=%s',
            user.username, quantity, str(e),
        )
        raise ValueError(f'Payment gateway error: {str(e)}')

    # Store local payment record
    RazorpayPayment.objects.create(
        user=user,
        payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
        razorpay_order_id=rz_order['id'],
        amount=amount_paise,
        currency=settings.RAZORPAY_CURRENCY,
        status=RazorpayPayment.STATUS_CREATED,
        notes={
            'quantity': quantity,
            'credits': credits_to_add,
            'plan_slug': plan.slug,
        },
    )

    logger.info(
        'Top-up order created: user=%s qty=%d credits=%d amount=₹%s order_id=%s',
        user.username, quantity, credits_to_add, total_price, rz_order['id'],
    )

    return {
        'order_id': rz_order['id'],
        'amount': amount_paise,
        'currency': settings.RAZORPAY_CURRENCY,
        'key_id': settings.RAZORPAY_KEY_ID,
        'quantity': quantity,
        'credits': credits_to_add,
        'total_price': float(total_price),
    }


def verify_topup_payment(
    user,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Verify a top-up payment after Razorpay checkout completes.

    1. Verify signature using HMAC-SHA256.
    2. Update RazorpayPayment record.
    3. Add credits to user's wallet.

    Returns result dict.
    """
    # Signature verification
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f'{razorpay_order_id}|{razorpay_payment_id}'.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, razorpay_signature):
        logger.warning(
            'Top-up payment signature mismatch: user=%s order_id=%s',
            user.username, razorpay_order_id,
        )
        raise ValueError('Payment verification failed: invalid signature.')

    return _fulfill_topup(user, razorpay_order_id, razorpay_payment_id, razorpay_signature)


@transaction.atomic
def _fulfill_topup(
    user,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str = '',
    via_webhook: bool = False,
) -> dict:
    """
    Internal: fulfill a top-up order and add credits.
    Idempotent — skips if already provisioned for this payment_id.
    """
    from .models import RazorpayPayment, WalletTransaction
    from .services import add_credits

    # Idempotency check
    existing = RazorpayPayment.objects.filter(
        razorpay_payment_id=razorpay_payment_id,
        credits_granted=True,
    ).first()
    if existing:
        logger.info('Top-up already processed (idempotent skip): payment_id=%s', razorpay_payment_id)
        return {
            'status': 'already_processed',
            'message': 'This payment has already been processed.',
            'payment_id': razorpay_payment_id,
        }

    # Find and update payment record
    payment = RazorpayPayment.objects.filter(
        razorpay_order_id=razorpay_order_id,
        status=RazorpayPayment.STATUS_CREATED,
    ).first()

    if not payment:
        # Could be webhook arriving before frontend, or duplicate
        logger.warning('Payment record not found for order_id=%s, creating new', razorpay_order_id)
        payment = RazorpayPayment(
            user=user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id=razorpay_order_id,
            amount=0,  # We'll fetch from Razorpay
            currency=settings.RAZORPAY_CURRENCY,
        )

    credits_to_add = payment.notes.get('credits', 0)
    quantity = payment.notes.get('quantity', 1)

    if credits_to_add == 0:
        # Try to derive from plan
        profile = user.profile
        plan = profile.plan
        if plan and plan.topup_credits_per_pack > 0:
            credits_to_add = plan.topup_credits_per_pack * quantity
        else:
            logger.error('Cannot determine credits for topup: order_id=%s', razorpay_order_id)
            raise ValueError('Unable to determine credit amount for this top-up.')

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.status = RazorpayPayment.STATUS_CAPTURED
    payment.webhook_verified = via_webhook
    payment.credits_granted = True
    payment.save()

    # Add credits to wallet
    result = add_credits(
        user=user,
        amount=credits_to_add,
        tx_type=WalletTransaction.TYPE_TOPUP,
        description=f'Top-up: {quantity} pack(s) × {credits_to_add // max(quantity, 1)} credits (Razorpay)',
        reference_id=razorpay_payment_id,
    )

    logger.info(
        'Top-up fulfilled: user=%s credits=%d payment_id=%s order_id=%s via=%s',
        user.username, credits_to_add, razorpay_payment_id, razorpay_order_id,
        'webhook' if via_webhook else 'frontend',
    )

    return {
        'status': 'success',
        'message': f'{credits_to_add} credits added to your wallet.',
        'credits_added': credits_to_add,
        'balance': result['balance_after'],
        'payment_id': razorpay_payment_id,
    }


# ── Webhook Handler ─────────────────────────────────────────────────────────

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify Razorpay webhook signature.
    Uses HMAC-SHA256 with the webhook secret.
    """
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_webhook_event(event: str, payload: dict) -> dict:
    """
    Process a Razorpay webhook event.

    Supported events:
    - payment.captured — payment completed successfully
    - subscription.activated — subscription is now active
    - subscription.charged — recurring payment collected
    - subscription.cancelled — subscription cancelled
    - subscription.completed — all cycles completed
    - subscription.halted — payment failed, subscription paused
    - payment.failed — payment attempt failed

    Returns a result dict with processing status.
    """
    from django.contrib.auth.models import User

    handler_map = {
        'payment.captured': _handle_payment_captured,
        'subscription.activated': _handle_subscription_activated,
        'subscription.charged': _handle_subscription_charged,
        'subscription.cancelled': _handle_subscription_status_change,
        'subscription.completed': _handle_subscription_status_change,
        'subscription.halted': _handle_subscription_status_change,
        'payment.failed': _handle_payment_failed,
    }

    handler = handler_map.get(event)
    if not handler:
        logger.info('Unhandled webhook event: %s', event)
        return {'status': 'ignored', 'event': event}

    try:
        return handler(payload)
    except Exception as e:
        logger.error('Webhook handler error: event=%s error=%s', event, str(e), exc_info=True)
        return {'status': 'error', 'event': event, 'error': str(e)}


def _handle_payment_captured(payload: dict) -> dict:
    """Handle payment.captured — for both subscriptions and top-ups."""
    from django.contrib.auth.models import User

    payment_entity = payload.get('payment', {}).get('entity', {})
    payment_id = payment_entity.get('id', '')
    order_id = payment_entity.get('order_id', '')
    notes = payment_entity.get('notes', {})
    user_id = notes.get('user_id')

    if not user_id:
        logger.warning('payment.captured webhook missing user_id in notes: payment_id=%s', payment_id)
        return {'status': 'skipped', 'reason': 'no user_id in notes'}

    try:
        user = User.objects.get(id=int(user_id))
    except User.DoesNotExist:
        logger.warning('payment.captured webhook: user not found: user_id=%s', user_id)
        return {'status': 'skipped', 'reason': 'user not found'}

    payment_type = notes.get('type', '')

    if payment_type == 'topup' and order_id:
        return _fulfill_topup(user, order_id, payment_id, via_webhook=True)

    return {'status': 'processed', 'payment_id': payment_id}


def _handle_subscription_activated(payload: dict) -> dict:
    """Handle subscription.activated — activate the subscription."""
    from django.contrib.auth.models import User

    sub_entity = payload.get('subscription', {}).get('entity', {})
    sub_id = sub_entity.get('id', '')
    notes = sub_entity.get('notes', {})
    user_id = notes.get('user_id')

    if not user_id:
        logger.warning('subscription.activated webhook missing user_id: sub_id=%s', sub_id)
        return {'status': 'skipped', 'reason': 'no user_id in notes'}

    try:
        user = User.objects.get(id=int(user_id))
    except User.DoesNotExist:
        return {'status': 'skipped', 'reason': 'user not found'}

    # Get the payment_id from the subscription entity
    payment_id = sub_entity.get('payment_id', '')

    if payment_id:
        return _activate_subscription(user, sub_id, payment_id, via_webhook=True)

    return {'status': 'processed', 'subscription_id': sub_id}


def _handle_subscription_charged(payload: dict) -> dict:
    """
    Handle subscription.charged — recurring payment collected.
    Extends the billing cycle and grants monthly credits.
    """
    from django.contrib.auth.models import User
    from .models import RazorpayPayment, RazorpaySubscription
    from .services import grant_monthly_credits_for_user

    sub_entity = payload.get('subscription', {}).get('entity', {})
    sub_id = sub_entity.get('id', '')
    payment_id = sub_entity.get('payment_id', '')
    notes = sub_entity.get('notes', {})
    user_id = notes.get('user_id')

    if not user_id:
        return {'status': 'skipped', 'reason': 'no user_id in notes'}

    try:
        user = User.objects.get(id=int(user_id))
    except User.DoesNotExist:
        return {'status': 'skipped', 'reason': 'user not found'}

    # Idempotency
    if payment_id and RazorpayPayment.objects.filter(
        razorpay_payment_id=payment_id, credits_granted=True,
    ).exists():
        return {'status': 'already_processed', 'payment_id': payment_id}

    with transaction.atomic():
        try:
            subscription = RazorpaySubscription.objects.select_for_update().get(
                razorpay_subscription_id=sub_id,
            )
        except RazorpaySubscription.DoesNotExist:
            return {'status': 'skipped', 'reason': 'subscription not found'}

        # Extend billing cycle
        subscription.current_start = timezone.now()
        subscription.current_end = timezone.now() + timezone.timedelta(days=30)
        subscription.status = RazorpaySubscription.STATUS_ACTIVE
        subscription.save()

        # Update user's plan_valid_until
        profile = user.profile
        profile.plan_valid_until = subscription.current_end
        profile.save(update_fields=['plan_valid_until'])

        # Grant monthly credits
        grant_monthly_credits_for_user(user, subscription.plan)

        # Record payment
        amount = int(subscription.plan.price * 100)
        RazorpayPayment.objects.create(
            user=user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_SUBSCRIPTION,
            razorpay_subscription_id=sub_id,
            razorpay_payment_id=payment_id,
            amount=amount,
            currency=settings.RAZORPAY_CURRENCY,
            status=RazorpayPayment.STATUS_CAPTURED,
            webhook_verified=True,
            credits_granted=True,
            notes={'event': 'subscription.charged', 'plan_slug': subscription.plan.slug},
        )

    logger.info(
        'Subscription charged: user=%s sub_id=%s payment_id=%s',
        user.username, sub_id, payment_id,
    )

    return {'status': 'processed', 'subscription_id': sub_id, 'payment_id': payment_id}


def _handle_subscription_status_change(payload: dict) -> dict:
    """Handle subscription status changes (cancelled, completed, halted)."""
    from .models import RazorpaySubscription

    sub_entity = payload.get('subscription', {}).get('entity', {})
    sub_id = sub_entity.get('id', '')
    new_status = sub_entity.get('status', '')

    try:
        subscription = RazorpaySubscription.objects.get(razorpay_subscription_id=sub_id)
        subscription.status = new_status
        subscription.save(update_fields=['status', 'updated_at'])

        logger.info('Subscription status updated: sub_id=%s status=%s', sub_id, new_status)

        # If halted or expired, process plan downgrade
        if new_status in ('halted', 'completed', 'expired'):
            from .services import subscribe_plan
            try:
                subscribe_plan(subscription.user, 'free')
                logger.info('User downgraded after subscription %s: user=%s',
                            new_status, subscription.user.username)
            except Exception as e:
                logger.error('Failed to downgrade user after subscription %s: %s', new_status, str(e))

        return {'status': 'processed', 'subscription_id': sub_id, 'new_status': new_status}
    except RazorpaySubscription.DoesNotExist:
        logger.warning('Subscription not found for status change: sub_id=%s', sub_id)
        return {'status': 'skipped', 'reason': 'subscription not found'}


def _handle_payment_failed(payload: dict) -> dict:
    """Handle payment.failed — mark payment as failed."""
    from .models import RazorpayPayment

    payment_entity = payload.get('payment', {}).get('entity', {})
    payment_id = payment_entity.get('id', '')
    order_id = payment_entity.get('order_id', '')

    # Try to find and update the payment record
    payment = RazorpayPayment.objects.filter(
        razorpay_order_id=order_id,
        status=RazorpayPayment.STATUS_CREATED,
    ).first()

    if payment:
        payment.razorpay_payment_id = payment_id
        payment.status = RazorpayPayment.STATUS_FAILED
        payment.webhook_verified = True
        payment.save()
        logger.info('Payment marked as failed: payment_id=%s order_id=%s', payment_id, order_id)
    else:
        logger.info('No matching payment record to mark as failed: payment_id=%s', payment_id)

    return {'status': 'processed', 'payment_id': payment_id}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_razorpay_plan_id(plan) -> str:
    """
    Get the Razorpay plan_id for a given Plan.

    Convention: Store in env as RAZORPAY_PLAN_ID_{SLUG_UPPER}.
    Falls back to a placeholder for development.
    """
    from django.conf import settings

    env_key = f'RAZORPAY_PLAN_ID_{plan.slug.upper()}'
    plan_id = getattr(settings, env_key, None)

    if not plan_id:
        # Try from decouple
        from decouple import config
        plan_id = config(env_key, default='')

    if not plan_id:
        # Development placeholder
        plan_id = f'plan_{plan.slug}_monthly'
        logger.warning(
            'Using placeholder Razorpay plan_id=%s for plan=%s. '
            'Set %s env var for production.',
            plan_id, plan.slug, env_key,
        )

    return plan_id


def get_payment_history(user, limit: int = 20) -> list:
    """Get recent payment history for a user."""
    from .models import RazorpayPayment

    payments = RazorpayPayment.objects.filter(user=user).order_by('-created_at')[:limit]
    return [
        {
            'id': p.id,
            'payment_type': p.payment_type,
            'razorpay_order_id': p.razorpay_order_id,
            'razorpay_payment_id': p.razorpay_payment_id or '',
            'amount': p.amount,
            'amount_display': f'₹{p.amount / 100:.2f}',
            'currency': p.currency,
            'status': p.status,
            'notes': p.notes,
            'created_at': p.created_at.isoformat(),
        }
        for p in payments
    ]
