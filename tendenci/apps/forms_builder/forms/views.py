import datetime

from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.mail import EmailMessage
from django.db.models import Q
from django.template import RequestContext
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, HttpResponse
from django.forms.models import inlineformset_factory
from django.contrib import messages
from django.utils.encoding import smart_str
from django.template.defaultfilters import yesno
from django.core.files.storage import default_storage

from tendenci.core.theme.shortcuts import themed_response as render_to_response
from tendenci.core.base.http import Http403
from tendenci.core.perms.utils import (has_perm, update_perms_and_save,
    get_query_filters, has_view_perm)
from tendenci.core.event_logs.models import EventLog
from tendenci.core.site_settings.utils import get_setting
from tendenci.apps.invoices.models import Invoice
from tendenci.addons.recurring_payments.models import RecurringPayment
from tendenci.core.exports.utils import run_export_task

from tendenci.apps.forms_builder.forms.forms import (FormForForm, FormForm, FormForField,
    PricingForm, BillingForm)
from tendenci.apps.forms_builder.forms.models import Form, Field, FormEntry, Pricing
from tendenci.apps.forms_builder.forms.utils import (generate_admin_email_body,
    generate_submitter_email_body, generate_email_subject,
    make_invoice_for_entry, update_invoice_for_entry)
from tendenci.apps.forms_builder.forms.formsets import BaseFieldFormSet

@login_required
def add(request, form_class=FormForm, template_name="forms/add.html"):
    if not has_perm(request.user,'forms.add_form'):
        raise Http403

    PricingFormSet = inlineformset_factory(Form, Pricing, form=PricingForm, extra=2, can_delete=False)

    formset = PricingFormSet()
    if request.method == "POST":
        form = form_class(request.POST, user=request.user)
        if form.is_valid():
            form_instance = form.save(commit=False)
            # save form and associated pricings
            form_instance = update_perms_and_save(request, form, form_instance)
            formset = PricingFormSet(request.POST, instance=form_instance)
            if formset.is_valid():
                # update_perms_and_save does not appear to consider ManyToManyFields
                for method in form.cleaned_data['payment_methods']:
                    form_instance.payment_methods.add(method)

                formset.save()

                messages.add_message(request, messages.SUCCESS, 'Successfully added %s' % form_instance)
                return HttpResponseRedirect(reverse('form_field_update', args=[form_instance.pk]))
    else:
        form = form_class(user=request.user)

    return render_to_response(template_name, {
        'form':form,
        'formset':formset,
    }, context_instance=RequestContext(request))


def edit(request, id, form_class=FormForm, template_name="forms/edit.html"):
    form_instance = get_object_or_404(Form, pk=id)

    if not has_perm(request.user,'forms.change_form',form_instance):
        raise Http403

    PricingFormSet = inlineformset_factory(Form, Pricing, form=PricingForm, extra=2)

    if request.method == "POST":
        form = form_class(request.POST, instance=form_instance, user=request.user)
        if form_instance.recurring_payment:
            formset = RecurringPaymentFormSet(request.POST, instance=form_instance)
        else:
            formset = PricingFormSet(request.POST, instance=form_instance)
        if form.is_valid() and formset.is_valid():
            form_instance = form.save(commit=False)
            form_instance = update_perms_and_save(request, form, form_instance)

            form.save_m2m()  # save payment methods
            formset.save()  # save price options

            # remove all pricings if no custom_payment form
            if not form.cleaned_data['custom_payment']:
                form_instance.pricing_set.all().delete()

            messages.add_message(request, messages.SUCCESS, 'Successfully edited %s' % form_instance)
            return HttpResponseRedirect(reverse('form_field_update', args=[form_instance.pk]))
    else:
        form = form_class(instance=form_instance, user=request.user)
        if form_instance.recurring_payment:
            formset = RecurringPaymentFormSet(instance=form_instance)
        else:
            formset = PricingFormSet(instance=form_instance)
    return render_to_response(template_name, {
        'form':form,
        'formset':formset,
        'form_instance':form_instance,
        },context_instance=RequestContext(request))


@login_required
def update_fields(request, id, template_name="forms/update_fields.html"):
    form_instance = get_object_or_404(Form, id=id)

    if not has_perm(request.user,'forms.add_form',form_instance):
        raise Http403

    form_class=inlineformset_factory(Form, Field, form=FormForField, formset=BaseFieldFormSet, extra=3)
    form_class._orderings = 'position'

    if request.method == "POST":
        form = form_class(request.POST, instance=form_instance, queryset=form_instance.fields.all().order_by('position'))
        if form.is_valid():
            form.save()

            messages.add_message(request, messages.SUCCESS, 'Successfully updated %s' % form_instance)
            return redirect('form_detail', form_instance.slug)
    else:
        form = form_class(instance=form_instance, queryset=form_instance.fields.all().order_by('position'))

    return render_to_response(template_name, {'form':form, 'form_instance':form_instance},
        context_instance=RequestContext(request))


@login_required
def delete(request, id, template_name="forms/delete.html"):
    form_instance = get_object_or_404(Form, pk=id)

    # check permission
    if not has_perm(request.user,'forms.delete_form',form_instance):
        raise Http403

    if request.method == "POST":
        messages.add_message(request, messages.SUCCESS, 'Successfully deleted %s' % form_instance)

        form_instance.delete()
        return HttpResponseRedirect(reverse('forms'))

    return render_to_response(template_name, {'form': form_instance},
        context_instance=RequestContext(request))

@login_required
def copy(request, id):
    """
    Copies a form_instance and all the fields related to it.
    """
    form_instance = get_object_or_404(Form, pk=id)

    # check permission
    if not (has_perm(request.user,'forms.add_form',form_instance) and
        has_perm(request.user,'forms.change_form',form_instance)):
            raise Http403

    # create a new slug
    slug = form_instance.slug
    if len(slug.rsplit('-', 1)) > 1 and slug.rsplit('-', 1)[1].isdigit():
        slug = slug.rsplit('-', 1)[0]
    i = 1
    while True:
        if i > 0:
            if i > 1:
                slug = slug.rsplit("-", 1)[0]
            slug = "%s-%s" % (slug, i)
        match = Form.objects.filter(slug=slug)
        if not match:
            break
        i += 1

    # copy the form
    new_form = Form.objects.create(
        title = form_instance.title,
        slug = slug,
        intro = form_instance.intro,
        response = form_instance.response,
        email_text = form_instance.email_text,
        subject_template = form_instance.subject_template,
        send_email = form_instance.send_email,
        email_from = form_instance.email_from,
        email_copies = form_instance.email_copies,
        completion_url = form_instance.completion_url,
        allow_anonymous_view = form_instance.allow_anonymous_view,
        allow_user_view = form_instance.allow_user_view,
        allow_member_view = form_instance.allow_member_view,
        allow_anonymous_edit = form_instance.allow_anonymous_edit,
        allow_user_edit = form_instance.allow_user_edit,
        allow_member_edit = form_instance.allow_member_edit,
        creator = request.user,
        creator_username = request.user.username,
        owner = request.user,
        owner_username = request.user.username,
        status = True,
        status_detail = 'draft',
        )

    # copy form fields
    for field in form_instance.fields.all():
        Field.objects.create(
            form = new_form,
            label = field.label,
            field_type = field.field_type,
            field_function = field.field_function,
            function_params = field.function_params,
            required = field.required,
            visible = field.visible,
            choices = field.choices,
            position = field.position,
            default = field.default,
            )

    messages.add_message(request, messages.SUCCESS, 'Successfully added %s' % new_form)
    return redirect('form_edit', new_form.pk)

@login_required
def entries(request, id, template_name="forms/entries.html"):
    form = get_object_or_404(Form, pk=id)

    if not has_perm(request.user,'forms.change_form',form):
        raise Http403

    entries = form.entries.all()

    EventLog.objects.log(instance=form)

    return render_to_response(template_name, {'form':form,'entries': entries},
        context_instance=RequestContext(request))


@login_required
def entry_delete(request, id, template_name="forms/entry_delete.html"):
    entry = get_object_or_404(FormEntry, pk=id)

    # check permission
    if not has_perm(request.user,'forms.delete_form',entry.form):
        raise Http403

    if request.method == "POST":
        messages.add_message(request, messages.SUCCESS, 'Successfully deleted entry %s' % entry)
        entry.delete()
        return HttpResponseRedirect(reverse('forms'))

    return render_to_response(template_name, {'entry': entry},
        context_instance=RequestContext(request))

@login_required
def entry_detail(request, id, template_name="forms/entry_detail.html"):
    entry = get_object_or_404(FormEntry, pk=id)

    # check permission
    if not has_perm(request.user,'forms.change_form',entry.form):
        raise Http403

    return render_to_response(template_name, {'entry':entry},
        context_instance=RequestContext(request))


def entries_export(request, id):
    form_instance = get_object_or_404(Form, pk=id)

    # check permission
    if not has_perm(request.user,'forms.change_form',form_instance):
        raise Http403

    EventLog.objects.log(instance=form_instance)

    entries = form_instance.entries.all()

    if entries:
        import csv
        import zipfile
        from os.path import join
        from os import unlink
        from time import time
        from tempfile import NamedTemporaryFile

        response = HttpResponse(mimetype='text/csv')
        response['Content-Disposition'] = 'attachment; filename=export_entries_%d.csv' % time()
        headers = []
        has_files = False

        # check for a field field
        for entry in entries:
            for field in entry.fields.all():
                if field.field.field_type == 'FileField':
                    has_files = True

        # if the object hase file store the csv elsewhere
        # so that we can zip the files
        if has_files:
            temp_csv = NamedTemporaryFile(mode='w', delete=False)
            temp_zip = NamedTemporaryFile(mode='wb', delete=False)
            writer = csv.writer(temp_csv, delimiter=',')
            zip = zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED)
        else:
            writer = csv.writer(response, delimiter=',')

        # get the header for headers for the csv
        headers.append('submitted on')
        for field in entries[0].fields.all():
            headers.append(smart_str(field.field.label))
        writer.writerow(headers)

        # write out the values
        for entry in entries:
            values = []
            values.append(entry.entry_time)
            for field in entry.fields.all():
                if has_files and field.field.field_type == 'FileField':
                    archive_name = join('files',field.value)
                    if hasattr(settings, 'USE_S3_STORAGE') and settings.USE_S3_STORAGE:
                        file_path = field.value
                        try:
                            # TODO: for large files, we may need to copy down
                            # the files before adding them to the zip file.
                            zip.writestr(archive_name, default_storage.open(file_path).read())
                        except IOError:
                            pass
                    else:
                        file_path = join(settings.MEDIA_ROOT,field.value)
                        zip.write(file_path, archive_name, zipfile.ZIP_DEFLATED)

                if field.field.field_type == 'BooleanField':
                    values.append(yesno(smart_str(field.value)))
                else:
                    values.append(smart_str(field.value))
            writer.writerow(values)

        # add the csv file to the zip, close it, and set the response
        if has_files:
            # add the csv file and close it all out
            temp_csv.close()
            zip.write(temp_csv.name, 'entries.csv', zipfile.ZIP_DEFLATED)
            zip.close()
            temp_zip.close()

            # set the response for the zip files
            response = HttpResponse(open(temp_zip.name,'rb'), mimetype='application/zip')
            response['Content-Disposition'] = 'attachment; filename=export_entries_%d.zip' % time()

            # remove the temporary files
            unlink(temp_zip.name)
            unlink(temp_csv.name)
    else:
        # blank csv document
        response = HttpResponse(mimetype='text/csv')
        response['Content-Disposition'] = 'attachment; filename=export_entries_%d.csv' % time()
        writer = csv.writer(response, delimiter=',')

    return response


def search(request, template_name="forms/search.html"):
    if not has_perm(request.user,'forms.view_form'):
        raise Http403

    filters = get_query_filters(request.user, 'forms.view_form')
    forms = Form.objects.filter(filters).distinct()
    query = request.GET.get('q', None)
    if query:
        forms = forms.filter(Q(title__icontains=query)|Q(intro__icontains=query)|Q(response__icontains=query))

    forms = forms.order_by('-pk')

    EventLog.objects.log()

    return render_to_response(template_name, {'forms':forms},
        context_instance=RequestContext(request))


def form_detail(request, slug, template="forms/form_detail.html"):
    """
    Display a built form and handle submission.
    """
    published = Form.objects.published(for_user=request.user)
    form = get_object_or_404(published, slug=slug)

    if not has_view_perm(request.user,'forms.view_form',form):
        raise Http403

    form_for_form = FormForForm(form, request.user, request.POST or None, request.FILES or None)

    for field in form_for_form.fields:
        field_default = request.GET.get(field, None)
        if field_default:
            form_for_form.fields[field].initial = field_default

    if request.method == "POST":
        if form_for_form.is_valid():
            entry = form_for_form.save()
            entry.entry_path = request.POST.get("entry_path", "")
            entry.save()

            # Email
            subject = generate_email_subject(form, entry)
            email_headers = {}  # content type specified below
            if form.email_from:
                email_headers.update({'Reply-To':form.email_from})

            # Email to submitter
            # fields aren't included in submitter body to prevent spam
            submitter_body = generate_submitter_email_body(entry, form_for_form)
            email_from = form.email_from or settings.DEFAULT_FROM_EMAIL
            sender = get_setting('site', 'global', 'siteemailnoreplyaddress')
            email_to = form_for_form.email_to()
            if email_to and form.send_email and form.email_text:
                # Send message to the person who submitted the form.
                msg = EmailMessage(subject, submitter_body, sender, [email_to], headers=email_headers)
                msg.content_subtype = 'html'
                msg.send()

            # Email copies to admin
            admin_body = generate_admin_email_body(entry, form_for_form)
            email_from = email_to or email_from # Send from the email entered.
            email_headers.update({'Reply-To':email_from})
            email_copies = [e.strip() for e in form.email_copies.split(",")
                if e.strip()]
            if email_copies:
                # Send message to the email addresses listed in the copies.
                msg = EmailMessage(subject, admin_body, sender, email_copies, headers=email_headers)
                msg.content_subtype = 'html'
                for f in form_for_form.files.values():
                    f.seek(0)
                    msg.attach(f.name, f.read())
                msg.send()

            # payment redirect
            if (form.custom_payment or form.recurring_payment) and entry.pricing:
                # get the pricing's price, custom or otherwise
                price = entry.pricing.price or form_for_form.cleaned_data.get('custom_price')

                if form.recurring_payment:
                    billing_start_dt = datetime.datetime.now()
                    trial_period_start_dt = None
                    trial_period_end_dt = None
                    if entry.pricing.has_trial_period:
                        trial_period_start_dt = datetime.datetime.now()
                        trial_period_end_dt = trial_period_start_dt + datetime.timedelta(1)
                        billing_start_dt = trial_period_end_dt
                    # Create recurring payment
                    rp = RecurringPayment(
                             user=request.user,
                             description=entry.pricing.label,
                             billing_period=entry.pricing.billing_period,
                             billing_start_dt=billing_start_dt,
                             num_days=entry.pricing.num_days,
                             due_sore=entry.pricing.due_sore,
                             payment_amount=price,
                             taxable=entry.pricing.taxable,
                             tax_rate=entry.pricing.tax_rate,
                             has_trial_period=entry.pricing.has_trial_period,
                             trial_period_start_dt=trial_period_start_dt,
                             trial_period_end_dt=trial_period_end_dt,
                             trial_amount=entry.pricing.trial_amount,
                             creator=request.user,
                             creator_username=request.user.username,
                             owner=request.user,
                             owner_username=request.user.username,
                         )
                    rp.save()
                    rp.add_customer_profile()

                    # redirect to recurring payments
                    messages.add_message(request, messages.SUCCESS, 'Successful transaction.')
                    return redirect('recurring_payment.my_accounts')
                else:
                    # create the invoice
                    invoice = make_invoice_for_entry(entry, custom_price=price)
                    # log an event for invoice add
                    log_defaults = {
                        'event_id' : 311000,
                        'event_data': '%s (%d) added by %s' % (invoice._meta.object_name, invoice.pk, request.user),
                        'description': '%s added' % invoice._meta.object_name,
                        'user': request.user,
                        'request': request,
                        'instance': invoice,
                    }
                    EventLog.objects.log(**log_defaults)

                    # redirect to billing form
                    return redirect('form_entry_payment', invoice.id, invoice.guid)

            # default redirect
            if form.completion_url:
                return redirect(form.completion_url)
            return redirect("form_sent", form.slug)
    context = {"form": form, "form_for_form": form_for_form}
    return render_to_response(template, context, RequestContext(request))

def form_sent(request, slug, template="forms/form_sent.html"):
    """
    Show the response message.
    """
    published = Form.objects.published(for_user=request.user)
    form = get_object_or_404(published, slug=slug)
    context = {"form": form}
    return render_to_response(template, context, RequestContext(request))

def form_entry_payment(request, invoice_id, invoice_guid, form_class=BillingForm, template="forms/form_payment.html"):
    """
    Show billing form, update the invoice then proceed to external payment.
    """
    invoice = get_object_or_404(Invoice, pk=invoice_id)

    if not invoice.allow_view_by(request.user, invoice_guid):
        raise Http403

    entry = FormEntry.objects.get(id=invoice.object_id)

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            update_invoice_for_entry(invoice, form)
            # redirect to online payment
            if (entry.payment_method.machine_name).lower() == 'credit-card':
                return redirect('payments.views.pay_online', invoice.id, invoice.guid)
            # redirect to invoice page
            return redirect('invoice.view', invoice.id, invoice.guid)
    else:
        if request.user.is_authenticated():
            form = form_class(initial={
                        'first_name':request.user.first_name,
                        'last_name':request.user.last_name,
                        'email':request.user.email})
        else:
            form = form_class()

    return render_to_response(template, {
            'payment_form':form,
            'form':entry.form,
        }, context_instance=RequestContext(request))

@login_required
def export(request, template_name="forms/export.html"):
    """Export forms"""

    if not request.user.is_superuser:
        raise Http403

    if request.method == 'POST':
        export_id = run_export_task('forms_builder.forms', 'form', [])
        EventLog.objects.log()
        return redirect('export.status', export_id)

    return render_to_response(template_name, {
    }, context_instance=RequestContext(request))


@login_required
def files(request, id):
    """
    Returns file.  Allows us to handle privacy.

    If default storage is remote:
        We can get data from remote location, convert to file
        object and return a file response.
    """

    import os
    import mimetypes
    from django.http import Http404
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from tendenci.core.perms.utils import has_view_perm
    from tendenci.apps.forms_builder.forms.models import FieldEntry

    field = get_object_or_404(FieldEntry, pk=id)
    form = field.field.form

    base_name = os.path.basename(field.value)
    mime_type = mimetypes.guess_type(base_name)[0]

    if not has_view_perm(request.user, 'forms.view_form', form):
        raise Http403

    if not mime_type:
        raise Http404

    if not default_storage.exists(field.value):
        raise Http404

    data = default_storage.open(field.value).read()
    f = ContentFile(data)

    response = HttpResponse(f.read(), mimetype=mime_type)
    response['Content-Disposition'] = 'filename=%s' % base_name
    return response
