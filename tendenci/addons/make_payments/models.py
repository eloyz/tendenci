import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

class MakePayment(models.Model):
    guid = models.CharField(max_length=50)
    user = models.ForeignKey(User, null=True)
    first_name = models.CharField(max_length=100, null=True)
    last_name = models.CharField(max_length=100, null=True)
    company = models.CharField(max_length=50, default='', blank=True, null=True)
    address = models.CharField(max_length=100, default='', blank=True, null=True)
    address2 = models.CharField(_('address line 2'), max_length=100, default='', blank=True, null=True)
    city = models.CharField(max_length=50, default='', blank=True, null=True)
    state = models.CharField(max_length=50, default='', blank=True, null=True)
    zip_code = models.CharField(max_length=50, default='', blank=True, null=True)
    country = models.CharField(max_length=50, default='', blank=True, null=True)
    email = models.CharField(max_length=50, default='',  null=True)
    phone = models.CharField(max_length=50, default='', blank=True, null=True)
    referral_source = models.CharField(_('referred by'), max_length=200, default='', blank=True, null=True)
    comments = models.TextField(blank=True, null=True)
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_count = models.IntegerField(blank=True, null=True)
    payment_method = models.CharField(max_length=50, default='cc')
    invoice_id = models.IntegerField(blank=True, null=True)
    create_dt = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(User, null=True,  related_name="make_payment_creator")
    creator_username = models.CharField(max_length=50, null=True)
    owner = models.ForeignKey(User, null=True, related_name="make_payment_owner")
    owner_username = models.CharField(max_length=50, null=True)
    status_detail = models.CharField(max_length=50, default='estimate')
    status = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("General Payment")
        verbose_name_plural = _("General Payments")

    def __unicode__(self):
        return 'Payment'
    
    def save(self, user=None):
        if not self.id:
            self.guid = str(uuid.uuid1())
            if user and user.id:
                self.creator=user
                self.creator_username=user.username
        if user and user.id:
            self.owner=user
            self.owner_username=user.username
            
        super(MakePayment, self).save()
        
    def allow_view_by(self, user2_compare):
        boo = False
        if user2_compare.profile.is_superuser:
            boo = True
        else: 
            if user2_compare and user2_compare.id > 0:
                if self.creator == user2_compare or self.owner == user2_compare:
                    if self.status == 1:
                        boo = True
            
        return boo
    
    # Called by payments_pop_by_invoice_user in Payment model.
    def get_payment_description(self, inv):
        """
        The description will be sent to payment gateway and displayed on invoice.
        If not supplied, the default description will be generated.
        """
        if self.comments:
            return 'Tendenci Invoice %d (Payment %d) %s' % (
                inv.id,
                inv.object_id,
                self.comments,
            )
        return
    
    def make_acct_entries(self, user, inv, amount, **kwargs):
        """
        Make the accounting entries for the general sale
        """
        from tendenci.apps.accountings.models import Acct, AcctEntry, AcctTran
        from tendenci.apps.accountings.utils import make_acct_entries_initial, make_acct_entries_closing
        
        ae = AcctEntry.objects.create_acct_entry(user, 'invoice', inv.id)
        if not inv.is_tendered:
            make_acct_entries_initial(user, ae, amount)
        else:
            # payment has now been received
            make_acct_entries_closing(user, ae, amount)
            
            # #CREDIT makepayment SALES
            acct_number = self.get_acct_number()
            acct = Acct.objects.get(account_number=acct_number)
            AcctTran.objects.create_acct_tran(user, ae, acct, amount*(-1)) 
            
    def get_acct_number(self, discount=False):
        if discount:
            return 466700
        else:
            return 406700
