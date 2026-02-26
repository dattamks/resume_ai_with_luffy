"""
Credit & wallet business logic.

All credit mutations go through this module to ensure:
- Atomic transactions with select_for_update() (no race conditions)
- Immutable audit trail via WalletTransaction
- No negative balances
- Consistent logging
"""
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('accounts')

# Default cost when CreditCost row is missing from DB
_DEFAULT_COSTS = {
    'resume_analysis': 1,
    'resume_generation': 1,
    'job_alert_run': 1,
}


class InsufficientCreditsError(Exception):
    """Raised when a user's wallet balance is too low for an action."""

    def __init__(self, balance, cost):
        self.balance = balance
        self.cost = cost
        super().__init__(f'Insufficient credits: balance={balance}, cost={cost}')


def get_credit_cost(action_slug: str) -> int:
    """
    Look up the credit cost for an action from the CreditCost table.
    Falls back to hardcoded defaults if the row doesn't exist.
    """
    from .models import CreditCost

    try:
        return CreditCost.objects.get(action=action_slug).cost
    except CreditCost.DoesNotExist:
        default = _DEFAULT_COSTS.get(action_slug, 0)
        if default:
            logger.warning(
                'CreditCost row missing for action=%s, using default=%d. '
                'Run `python manage.py seed_credit_costs` to fix.',
                action_slug, default,
            )
        return default


def check_balance(user, action_slug: str) -> dict:
    """
    Check if user has enough credits for an action.
    Returns dict with has_enough, balance, cost.
    """
    from .models import Wallet

    cost = get_credit_cost(action_slug)
    try:
        wallet = Wallet.objects.get(user=user)
        balance = wallet.balance
    except Wallet.DoesNotExist:
        balance = 0

    return {
        'has_enough': balance >= cost,
        'balance': balance,
        'cost': cost,
    }


@transaction.atomic
def deduct_credits(user, action_slug: str, description: str = '', reference_id: str = '') -> dict:
    """
    Atomically deduct credits for an action.

    Uses select_for_update() to prevent race conditions.
    Raises InsufficientCreditsError if balance is too low.

    Returns dict with balance_before, balance_after, cost.
    """
    from .models import Wallet, WalletTransaction

    cost = get_credit_cost(action_slug)
    if cost == 0:
        # Free action — no wallet interaction needed
        return {'balance_before': 0, 'balance_after': 0, 'cost': 0}

    wallet = Wallet.objects.select_for_update().get(user=user)
    balance_before = wallet.balance

    if balance_before < cost:
        raise InsufficientCreditsError(balance_before, cost)

    wallet.balance = balance_before - cost
    wallet.save(update_fields=['balance', 'updated_at'])

    WalletTransaction.objects.create(
        wallet=wallet,
        amount=-cost,
        balance_after=wallet.balance,
        transaction_type=WalletTransaction.TYPE_ANALYSIS_DEBIT,
        description=description or f'{action_slug} credit deduction',
        reference_id=str(reference_id),
    )

    logger.info(
        'Credits deducted: user=%s action=%s cost=%d balance=%d→%d ref=%s',
        user.username, action_slug, cost, balance_before, wallet.balance, reference_id,
    )
    return {
        'balance_before': balance_before,
        'balance_after': wallet.balance,
        'cost': cost,
    }


@transaction.atomic
def refund_credits(user, action_slug: str, description: str = '', reference_id: str = '') -> dict:
    """
    Refund credits for a failed action.

    Returns dict with balance_before, balance_after, cost.
    Silently skips if wallet doesn't exist (user deleted).
    """
    from .models import Wallet, WalletTransaction

    cost = get_credit_cost(action_slug)
    if cost == 0:
        return {'balance_before': 0, 'balance_after': 0, 'cost': 0}

    try:
        wallet = Wallet.objects.select_for_update().get(user=user)
    except Wallet.DoesNotExist:
        logger.warning('Refund skipped: wallet not found for user_id=%s', user.id)
        return {'balance_before': 0, 'balance_after': 0, 'cost': cost}

    balance_before = wallet.balance
    wallet.balance = balance_before + cost
    wallet.save(update_fields=['balance', 'updated_at'])

    WalletTransaction.objects.create(
        wallet=wallet,
        amount=cost,
        balance_after=wallet.balance,
        transaction_type=WalletTransaction.TYPE_REFUND,
        description=description or f'{action_slug} refund (analysis failed)',
        reference_id=str(reference_id),
    )

    logger.info(
        'Credits refunded: user=%s action=%s cost=%d balance=%d→%d ref=%s',
        user.username, action_slug, cost, balance_before, wallet.balance, reference_id,
    )
    return {
        'balance_before': balance_before,
        'balance_after': wallet.balance,
        'cost': cost,
    }


@transaction.atomic
def add_credits(user, amount: int, tx_type: str, description: str = '', reference_id: str = '') -> dict:
    """
    Add credits to a user's wallet (for monthly grants, top-ups, admin adjustments).

    Returns dict with balance_before, balance_after, amount.
    """
    from .models import Wallet, WalletTransaction

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    balance_before = wallet.balance
    wallet.balance = balance_before + amount
    wallet.save(update_fields=['balance', 'updated_at'])

    WalletTransaction.objects.create(
        wallet=wallet,
        amount=amount,
        balance_after=wallet.balance,
        transaction_type=tx_type,
        description=description,
        reference_id=str(reference_id),
    )

    logger.info(
        'Credits added: user=%s amount=%d type=%s balance=%d→%d',
        user.username, amount, tx_type, balance_before, wallet.balance,
    )
    return {
        'balance_before': balance_before,
        'balance_after': wallet.balance,
        'amount': amount,
    }


@transaction.atomic
def topup_credits(user, quantity: int = 1) -> dict:
    """
    Process a top-up purchase for a Pro user.

    Validates:
    - User's plan supports top-ups (topup_credits_per_pack > 0)
    - No pending downgrade
    - Quantity >= 1

    Returns dict with credits_added, balance_after, total_price.
    Raises ValueError on validation failure.
    """
    from .models import Wallet, WalletTransaction

    profile = user.profile
    plan = profile.plan

    if not plan or plan.topup_credits_per_pack == 0:
        raise ValueError('Your plan does not support credit top-ups.')

    if profile.pending_plan is not None:
        raise ValueError('Cannot top up while a plan downgrade is pending.')

    if quantity < 1:
        raise ValueError('Quantity must be at least 1.')

    credits_to_add = plan.topup_credits_per_pack * quantity
    total_price = plan.topup_price * quantity

    wallet = Wallet.objects.select_for_update().get(user=user)
    balance_before = wallet.balance
    wallet.balance = balance_before + credits_to_add
    wallet.save(update_fields=['balance', 'updated_at'])

    WalletTransaction.objects.create(
        wallet=wallet,
        amount=credits_to_add,
        balance_after=wallet.balance,
        transaction_type=WalletTransaction.TYPE_TOPUP,
        description=f'Top-up: {quantity} pack(s) × {plan.topup_credits_per_pack} credits = {credits_to_add} credits',
    )

    logger.info(
        'Top-up: user=%s qty=%d credits=%d price=₹%s balance=%d→%d',
        user.username, quantity, credits_to_add, total_price, balance_before, wallet.balance,
    )
    return {
        'credits_added': credits_to_add,
        'balance_before': balance_before,
        'balance_after': wallet.balance,
        'total_price': float(total_price),
    }


@transaction.atomic
def subscribe_plan(user, plan_slug: str) -> dict:
    """
    Switch user's plan.

    Upgrade (e.g., free → pro):
    - Immediately changes plan
    - Grants plan credits as upgrade bonus
    - Sets plan_valid_until = now + 30 days

    Downgrade (e.g., pro → free):
    - Sets pending_plan — user stays on current plan until plan_valid_until
    - If plan_valid_until already passed or is None, downgrades immediately

    Same plan:
    - Returns current state, no changes

    Returns dict describing the action taken.
    """
    from .models import Plan, Wallet, WalletTransaction

    try:
        new_plan = Plan.objects.get(slug=plan_slug, is_active=True)
    except Plan.DoesNotExist:
        raise ValueError(f'Plan "{plan_slug}" not found or inactive.')

    profile = user.profile
    current_plan = profile.plan

    # Same plan — no-op
    if current_plan and current_plan.slug == plan_slug:
        return {
            'action': 'none',
            'message': f'Already on the {current_plan.name} plan.',
            'plan': current_plan.slug,
        }

    current_order = current_plan.display_order if current_plan else 0
    new_order = new_plan.display_order

    if new_order > current_order:
        # ── Upgrade ──
        profile.plan = new_plan
        profile.plan_valid_until = timezone.now() + timezone.timedelta(days=30)
        profile.pending_plan = None  # Clear any pending downgrade
        profile.save(update_fields=['plan', 'plan_valid_until', 'pending_plan'])

        # Grant upgrade bonus credits
        if new_plan.credits_per_month > 0:
            wallet = Wallet.objects.select_for_update().get(user=user)
            balance_before = wallet.balance
            wallet.balance += new_plan.credits_per_month
            wallet.save(update_fields=['balance', 'updated_at'])

            WalletTransaction.objects.create(
                wallet=wallet,
                amount=new_plan.credits_per_month,
                balance_after=wallet.balance,
                transaction_type=WalletTransaction.TYPE_UPGRADE_BONUS,
                description=f'Upgrade to {new_plan.name}: {new_plan.credits_per_month} bonus credits',
            )

        logger.info('Plan upgraded: user=%s %s→%s', user.username,
                     current_plan.slug if current_plan else 'none', plan_slug)
        return {
            'action': 'upgraded',
            'message': f'Upgraded to {new_plan.name}. {new_plan.credits_per_month} bonus credits added.',
            'plan': new_plan.slug,
            'plan_valid_until': profile.plan_valid_until.isoformat(),
        }
    else:
        # ── Downgrade ──
        # If plan_valid_until is in the future, schedule downgrade
        if profile.plan_valid_until and profile.plan_valid_until > timezone.now():
            profile.pending_plan = new_plan
            profile.save(update_fields=['pending_plan'])

            logger.info('Plan downgrade scheduled: user=%s %s→%s at %s',
                         user.username, current_plan.slug, plan_slug, profile.plan_valid_until)
            return {
                'action': 'downgrade_scheduled',
                'message': (
                    f'Downgrade to {new_plan.name} scheduled. '
                    f'You will remain on {current_plan.name} until {profile.plan_valid_until.strftime("%B %d, %Y")}. '
                    f'Your credit balance carries forward.'
                ),
                'plan': current_plan.slug,
                'pending_plan': new_plan.slug,
                'effective_date': profile.plan_valid_until.isoformat(),
            }
        else:
            # Immediate downgrade (free plan or expired billing cycle)
            profile.plan = new_plan
            profile.plan_valid_until = None
            profile.pending_plan = None
            profile.save(update_fields=['plan', 'plan_valid_until', 'pending_plan'])

            logger.info('Plan downgraded immediately: user=%s %s→%s',
                         user.username, current_plan.slug if current_plan else 'none', plan_slug)
            return {
                'action': 'downgraded',
                'message': f'Downgraded to {new_plan.name}. Your credit balance carries forward.',
                'plan': new_plan.slug,
            }


def process_expired_plans():
    """
    Process all users whose plan_valid_until has passed and have a pending_plan.
    Called by a periodic Celery task (monthly or daily).

    For each expired user:
    - Switch to pending_plan
    - Grant new plan's monthly credits (with cap)
    - Clear pending_plan and plan_valid_until
    """
    from .models import UserProfile, WalletTransaction

    now = timezone.now()
    expired_profiles = UserProfile.objects.filter(
        plan_valid_until__lte=now,
        pending_plan__isnull=False,
    ).select_related('user', 'plan', 'pending_plan')

    count = 0
    for profile in expired_profiles:
        with transaction.atomic():
            old_plan = profile.plan
            new_plan = profile.pending_plan
            profile.plan = new_plan
            profile.pending_plan = None
            profile.plan_valid_until = None
            profile.save(update_fields=['plan', 'pending_plan', 'plan_valid_until'])

            # Grant monthly credits for the new plan (with cap)
            if new_plan and new_plan.credits_per_month > 0:
                grant_monthly_credits_for_user(profile.user, new_plan)

            count += 1
            logger.info(
                'Plan expired: user=%s switched %s→%s',
                profile.user.username,
                old_plan.slug if old_plan else 'none',
                new_plan.slug if new_plan else 'none',
            )

    if count:
        logger.info('Processed %d expired plan(s)', count)
    return count


def grant_monthly_credits_for_user(user, plan=None):
    """
    Grant monthly credits to a single user, respecting the plan's max_credits_balance cap.
    Top-ups are not affected by this cap.
    """
    from .models import Wallet, WalletTransaction

    if plan is None:
        plan = user.profile.plan

    if not plan or plan.credits_per_month == 0:
        return

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    balance_before = wallet.balance

    # Calculate how many credits to grant (cap applies to monthly grants only)
    credits_to_grant = plan.credits_per_month
    if plan.max_credits_balance > 0:
        room = max(0, plan.max_credits_balance - wallet.balance)
        credits_to_grant = min(credits_to_grant, room)

    if credits_to_grant <= 0:
        logger.info(
            'Monthly grant skipped for user=%s: balance=%d already at cap=%d',
            user.username, wallet.balance, plan.max_credits_balance,
        )
        return

    wallet.balance += credits_to_grant
    wallet.save(update_fields=['balance', 'updated_at'])

    WalletTransaction.objects.create(
        wallet=wallet,
        amount=credits_to_grant,
        balance_after=wallet.balance,
        transaction_type=WalletTransaction.TYPE_PLAN_CREDIT,
        description=f'Monthly {plan.name} plan grant ({credits_to_grant} credits)',
    )

    logger.info(
        'Monthly credits granted: user=%s plan=%s credits=%d balance=%d→%d',
        user.username, plan.slug, credits_to_grant, balance_before, wallet.balance,
    )


def can_use_feature(user, feature_name: str) -> bool:
    """Check if user's plan allows a specific feature flag."""
    profile = getattr(user, 'profile', None)
    if not profile or not profile.plan:
        return False
    return getattr(profile.plan, feature_name, False)
