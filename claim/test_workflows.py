import html5lib
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from core.dates import clean_datetime
from .models import Claim, ClaimType, Journal, LineTable, RoStatus, Status, Tag
from accounts.models import Dealership


class ContributorWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = Dealership.objects.create(name='Workflow Dealer')
        cls.foreign = Dealership.objects.create(name='Foreign Workflow')
        cls.user = get_user_model().objects.create_user(email='workflow@example.invalid')
        cls.user.groups.add(Group.objects.create(name='dealer-admin'))
        cls.user.dealership.add(cls.dealer)
        cls.admin = get_user_model().objects.create_superuser(email='workflow-admin@example.invalid')
        # Deliberately different from production IDs.
        Status.objects.create(name='Unrelated')
        cls.statuses = {name: Status.objects.create(name=name) for name in (
            'Rejected', 'Paid', 'New', 'Rework', 'Not Submitted', 'Pending', 'No Warranty', 'Requires Attention')}
        cls.open = RoStatus.objects.create(name='Open')
        cls.tag = Tag.objects.create(name='Warranty')
        cls.type = ClaimType.objects.create(name='Warranty')
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=900, ro_status=cls.open)
        cls.line = LineTable.objects.create(claim=cls.claim, dealership=cls.dealer, claim_type=cls.type,
            claim_status=cls.statuses['Requires Attention'], start_date=clean_datetime('2026-10-08T14:32:10'))

    def setUp(self):
        self.client.force_login(self.user)
        self.create_url = reverse('claim:claim-form', args=[self.dealer.pk])
        self.edit_url = reverse('claim:dealer-claim-update', args=[self.claim.pk, self.dealer.pk])
        self.update_url = reverse('claim:line-updates')

    def set_status(self, name):
        LineTable.objects.filter(pk=self.line.pk).update(claim_status=self.statuses[name])

    def status_select(self, response):
        root = html5lib.parse(response.content.decode(), namespaceHTMLElements=False)
        form = next(node for node in root.iter('form') if node.get('id') == f'line_form_{self.line.pk}')
        return next(node for node in form.iter('select') if node.get('name') == 'claim_status')

    def test_status_options_and_defaults_follow_each_current_status(self):
        for current, choices, selected in (
            ('Requires Attention', {'Rework', 'Not Submitted'}, 'Rework'),
            ('Rejected', {'Rejected', 'Rework'}, 'Rejected'),
            ('No Warranty', {'No Warranty', 'Rework'}, 'No Warranty'),
            ('Not Submitted', {'Not Submitted', 'Rework'}, 'Not Submitted'),
        ):
            with self.subTest(current=current):
                self.set_status(current)
                select = self.status_select(self.client.get(self.edit_url))
                self.assertEqual({option.text.strip() for option in select}, choices)
                chosen = [option for option in select if 'selected' in option.attrib]
                self.assertEqual([option.text.strip() for option in chosen], [selected])
                for option in select:
                    self.assertEqual(option.get('value'), str(self.statuses[option.text.strip()].pk))
                    if current != 'Requires Attention' and option.text.strip() == 'Rework':
                        self.assertEqual(option.get('data-comment-required'), 'true')

    def test_disallowed_transitions_are_rejected_even_with_forged_post(self):
        for current, target in (('Requires Attention', 'No Warranty'), ('Requires Attention', 'Rejected'),
            ('Rejected', 'Not Submitted'), ('No Warranty', 'Rejected'), ('Not Submitted', 'No Warranty'), ('Paid', 'Rework')):
            with self.subTest(current=current, target=target):
                self.set_status(current)
                response = self.client.post(self.update_url, {'line_id': self.line.pk,
                    'claim_status': self.statuses[target].pk, 'comment': 'Attempt forbidden transition'})
                self.assertEqual(response.status_code, 403)
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status, self.statuses[current])
        self.assertFalse(Journal.objects.exists())

    def test_return_to_rework_requires_comment_and_preserves_draft(self):
        for current in ('Rejected', 'No Warranty', 'Not Submitted'):
            with self.subTest(current=current):
                self.set_status(current)
                response = self.client.post(self.update_url, {'line_id': self.line.pk,
                    'claim_status': self.statuses['Rework'].pk, 'comment': '   '})
                self.assertEqual(response.status_code, 302)
                response = self.client.get(response.url)
                self.assertContains(response, 'A comment is required')
                self.assertEqual([option.text.strip() for option in self.status_select(response)
                    if 'selected' in option.attrib], ['Rework'])
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status, self.statuses[current])
                response = self.client.post(self.update_url, {'line_id': self.line.pk,
                    'claim_status': self.statuses['Rework'].pk, 'comment': f'Resolved {current}'})
                self.assertEqual(response.status_code, 302)
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status, self.statuses['Rework'])
                self.assertTrue(Journal.objects.filter(line=self.line, comment=f'Resolved {current}').exists())

    def test_attention_to_rework_needs_no_comment_and_keeps_timestamp_precision(self):
        stamp = self.line.start_date.replace(microsecond=123456)
        LineTable.objects.filter(pk=self.line.pk).update(start_date=stamp)
        response = self.client.post(self.update_url, {'line_id': self.line.pk, 'claim_status': self.statuses['Rework'].pk})
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_status, self.statuses['Rework'])
        self.assertEqual(self.line.start_date, stamp)
        self.assertFalse(Journal.objects.exists())

    def test_attention_to_not_submitted_retains_existing_comment_requirement(self):
        response = self.client.post(self.update_url, {'line_id': self.line.pk, 'claim_status': self.statuses['Not Submitted'].pk})
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_status, self.statuses['Requires Attention'])
        response = self.client.post(self.update_url, {'line_id': self.line.pk,
            'claim_status': self.statuses['Not Submitted'].pk, 'comment': 'Will not submit'})
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_status, self.statuses['Not Submitted'])

    def payload(self, number, action='submit'):
        return {'dealership': self.dealer.pk, 'repair_order': number, 'claim_tag': [self.tag.pk],
            'comment': f'Evidence for {number}', 'action': action}

    def test_submit_opens_created_claim_for_dealer_and_admin(self):
        for user, number, route in ((self.user, 901, 'dealer-claim-update'), (self.admin, 902, 'claim-update')):
            self.client.force_login(user)
            response = self.client.post(self.create_url, self.payload(number))
            claim = Claim.objects.get(repair_order=number)
            self.assertRedirects(response, reverse('claim:' + route, args=[claim.pk, self.dealer.pk]))
            self.assertEqual(claim.linetable_set.get().claim_status, self.statuses['New'])
            self.assertTrue(claim.journal_set.filter(comment=f'Evidence for {number}').exists())
            self.assertEqual(list(claim.claim_tag.all()), [self.tag])

    def test_add_another_repeats_with_fresh_form_and_done_without_saving(self):
        for number in (910, 911, 912):
            response = self.client.post(self.create_url, self.payload(number, 'add_another'))
            self.assertEqual(response.url, self.create_url + '?add_another=1')
            response = self.client.get(response.url)
            self.assertFalse(response.context['claim_form'].is_bound)
            self.assertFalse(response.context['journal_form'].is_bound)
            self.assertTrue(response.context['adding_multiple'])
            self.assertNotContains(response, f'Evidence for {number}')
            self.assertContains(response, f'href="{reverse("dashboard:dashboard")}"')
            self.assertContains(response, '>Done</a>')
            count = Claim.objects.count()
            self.client.get(self.create_url + '?add_another=1')
            self.assertEqual(Claim.objects.count(), count)
        count = Claim.objects.count()
        self.client.get(reverse('dashboard:dashboard'))
        self.assertEqual(Claim.objects.count(), count)
        self.assertNotContains(self.client.get(self.create_url), '>Done</a>')

    def test_invalid_batch_submission_preserves_fields_and_creates_nothing(self):
        payload = self.payload(920, 'add_another')
        payload['repair_order'] = 'invalid'
        before = Claim.objects.count()
        response = self.client.post(self.create_url + '?add_another=1', payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="invalid"')
        self.assertContains(response, 'Evidence for 920')
        self.assertContains(response, 'checked')
        self.assertContains(response, '>Done</a>')
        self.assertEqual(Claim.objects.count(), before)
        self.assertFalse(Journal.objects.exists())

    def test_duplicate_and_foreign_claim_creation_remain_blocked(self):
        for action in ('submit', 'add_another'):
            before = Claim.objects.count()
            response = self.client.post(self.create_url, self.payload(900, action))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'already exists')
            payload = self.payload(930, action)
            payload['dealership'] = self.foreign.pk
            self.assertEqual(self.client.post(self.create_url, payload).status_code, 200)
            self.assertEqual(Claim.objects.count(), before)
            self.assertEqual(self.client.post(reverse('claim:claim-form', args=[self.foreign.pk]), payload).status_code, 404)
        self.assertEqual(self.client.post(self.create_url, self.payload(940, 'unknown')).status_code, 400)
