from django.test import TestCase
from django.urls import reverse

from .models import User


class UserAdminProgressionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='root', email='root@example.com', password='pw-for-tests-only',
        )
        self.member = User.objects.create_user(username='critic', password='pw-for-tests-only')
        self.client.force_login(self.admin)

    def test_user_list_shows_progression_columns(self):
        response = self.client.get(reverse('admin:accounts_user_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'critic')
        self.assertContains(response, 'Achievements')
        self.assertContains(response, 'Frames unlocked')

    def test_user_change_page_shows_achievements_badges_and_frames(self):
        response = self.client.get(reverse('admin:accounts_user_change', args=[self.member.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Film critic (write 10 reviews)')
        self.assertContains(response, 'Well argued')
        self.assertContains(response, 'Newcomer (everyone, from level 1)')
        self.assertContains(response, 'Local cinema (not tracked yet)')

    def test_add_user_page_loads_without_progression(self):
        response = self.client.get(reverse('admin:accounts_user_add'))

        self.assertEqual(response.status_code, 200)
