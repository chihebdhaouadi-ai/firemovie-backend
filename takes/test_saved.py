from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import SavedTake, Tag, Take

FILM = 'tt0137523'


class SavedTakeTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.topic = Take.objects.create(
            film_id=FILM, author=self.ana, tag=Tag.QUESTION, body='Are we free?',
        )
        self.client.force_authenticate(self.me)

    def save(self, take, active=True):
        return self.client.put(f'/api/takes/takes/{take.id}/save/', {'active': active}, format='json')

    def test_saving_marks_the_take_and_unsaving_clears_it(self):
        saved = self.save(self.topic)

        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.data['is_saved'])
        self.assertTrue(SavedTake.objects.filter(take=self.topic, user=self.me).exists())
        # Saving twice keeps one save.
        self.save(self.topic)
        self.assertEqual(SavedTake.objects.filter(take=self.topic).count(), 1)

        unsaved = self.save(self.topic, active=False)
        self.assertFalse(unsaved.data['is_saved'])
        self.assertFalse(SavedTake.objects.exists())

    def test_you_cannot_save_your_own_take(self):
        mine = Take.objects.create(film_id=FILM, author=self.me, tag=Tag.QUESTION, body='Mine')

        self.assertEqual(self.save(mine).status_code, 400)

    def test_saved_list_shows_what_you_saved_newest_first_with_the_film(self):
        other = Take.objects.create(film_id=FILM, author=self.ana, tag=Tag.DISCUSSION, body='Ending?')
        self.save(self.topic)
        self.save(other)

        data = self.client.get('/api/takes/saved/').data

        self.assertEqual([item['id'] for item in data], [other.id, self.topic.id])
        self.assertTrue(all(item['is_saved'] for item in data))
        self.assertEqual(data[0]['film']['film_id'], FILM)

    def test_feeds_say_whether_each_take_is_saved(self):
        self.save(self.topic)

        trending = self.client.get('/api/takes/topics/trending/').data

        self.assertTrue(next(item for item in trending if item['id'] == self.topic.id)['is_saved'])

    def test_someone_elses_saves_are_not_yours(self):
        self.save(self.topic)
        self.client.force_authenticate(self.ana)

        self.assertEqual(self.client.get('/api/takes/saved/').data, [])
