from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Tag, Take, TakeComment, TakeVote, VoteKind
from .reputation import level_for_xp, period_start, progress_for, total_xp

FILM = 'tt0111161'


def review(author, film, at=None):
    take = Take.objects.create(film_id=film, author=author, tag=Tag.REVIEW, body='Take')
    if at is not None:
        Take.objects.filter(pk=take.pk).update(created_at=at)
    return take


def vote(take, voter, kind=VoteKind.WELL_ARGUED, at=None):
    created = TakeVote.objects.create(take=take, user=voter, kind=kind)
    if at is not None:
        TakeVote.objects.filter(pk=created.pk).update(created_at=at)
    return created


def reactions_by_username(entries):
    return {entry['username']: entry['reactions'] for entry in entries}


class LeaderboardTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.cara = User.objects.create_user(username='cara', password='pw-123456')
        self.client.force_authenticate(self.viewer)

    def board(self, period='all'):
        response = self.client.get('/api/takes/leaderboard/', {'period': period})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_each_voter_counts_once_per_review(self):
        take = review(self.ana, FILM)
        vote(take, self.ben, VoteKind.WELL_ARGUED)
        vote(take, self.ben, VoteKind.CHANGED_MY_MIND)
        vote(take, self.cara, VoteKind.DISAGREE_BUT_FAIR)

        data = self.board()

        self.assertEqual(reactions_by_username(data['entries']), {'ana': 2})

    def test_self_votes_never_count(self):
        take = review(self.ana, FILM)
        vote(take, self.ana, VoteKind.WELL_ARGUED)

        data = self.board()

        self.assertEqual(data['entries'], [])
        self.assertIsNone(data['me']['rank'])

    def test_only_review_takes_count(self):
        question = Take.objects.create(film_id=FILM, author=self.ana, tag=Tag.QUESTION, body='Why?')
        vote(question, self.ben)

        self.assertEqual(self.board()['entries'], [])

    def test_week_window_starts_monday_midnight(self):
        start = period_start('week')
        take = review(self.ana, FILM)
        vote(take, self.ben, at=start - timedelta(seconds=1))
        vote(take, self.cara, at=start)

        self.assertEqual(reactions_by_username(self.board('week')['entries']), {'ana': 1})
        self.assertEqual(reactions_by_username(self.board('all')['entries']), {'ana': 2})

    def test_month_window_starts_on_the_first(self):
        start = period_start('month')
        take = review(self.ana, FILM)
        vote(take, self.ben, at=start - timedelta(seconds=1))
        vote(take, self.cara, at=start)

        self.assertEqual(reactions_by_username(self.board('month')['entries']), {'ana': 1})
        self.assertEqual(reactions_by_username(self.board('all')['entries']), {'ana': 2})

    def test_reaction_time_is_the_voters_earliest_vote_on_the_take(self):
        start = period_start('week')
        take = review(self.ana, FILM)
        vote(take, self.ben, VoteKind.WELL_ARGUED, at=start - timedelta(seconds=1))
        vote(take, self.ben, VoteKind.CHANGED_MY_MIND, at=start + timedelta(seconds=1))

        self.assertEqual(self.board('week')['entries'], [])
        self.assertEqual(reactions_by_username(self.board('all')['entries']), {'ana': 1})

    def test_reviews_count_only_reviews_inside_the_period(self):
        start = period_start('week')
        review(self.ana, 'tt0000001', at=start - timedelta(seconds=1))
        current = review(self.ana, 'tt0000002')
        vote(current, self.ben)

        week = self.board('week')['entries'][0]
        self.assertEqual((week['username'], week['reviews'], week['reactions']), ('ana', 1, 1))
        self.assertEqual(self.board('all')['entries'][0]['reviews'], 2)

    def test_ties_rank_by_who_reached_the_total_first(self):
        now = timezone.now()
        ana_take = review(self.ana, 'tt0000001')
        ben_take = review(self.ben, 'tt0000002')
        vote(ana_take, self.cara, at=now - timedelta(hours=3))
        vote(ana_take, self.viewer, at=now - timedelta(hours=1))
        vote(ben_take, self.cara, at=now - timedelta(hours=3))
        vote(ben_take, self.viewer, at=now - timedelta(hours=2))

        names = [entry['username'] for entry in self.board()['entries']]

        self.assertEqual(names, ['ben', 'ana'])

    def test_entries_have_the_contract_shape(self):
        take = review(self.ana, FILM)
        vote(take, self.ben)

        entry = self.board()['entries'][0]

        self.assertEqual(entry, {
            'rank': 1,
            'user_id': self.ana.id,
            'username': 'ana',
            'avatar': None,
            'equipped_frame': 'bronze',
            'reviews': 1,
            'reactions': 1,
        })

    def test_viewer_outside_top_twenty_gets_a_real_rank(self):
        base = timezone.now()
        for index in range(21):
            author = get_user_model().objects.create_user(
                username=f'author{index}', password='pw-123456',
            )
            take = review(author, f'tt{index:07d}')
            vote(take, self.cara, at=base - timedelta(hours=30 - index))
        viewer_take = review(self.viewer, 'tt9999999')
        vote(viewer_take, self.cara, at=base - timedelta(minutes=5))

        data = self.board()

        self.assertEqual(len(data['entries']), 20)
        self.assertNotIn('viewer', [entry['username'] for entry in data['entries']])
        self.assertEqual(data['me']['rank'], 22)
        self.assertEqual(data['me']['reactions'], 1)
        self.assertEqual(data['me']['reviews'], 1)

    def test_viewer_without_reactions_has_null_rank(self):
        review(self.viewer, FILM)
        vote(review(self.ana, 'tt0000001'), self.ben)

        data = self.board('week')

        self.assertIsNone(data['me']['rank'])
        self.assertEqual(data['me']['reactions'], 0)
        self.assertEqual(data['me']['reviews'], 1)

    def test_invalid_period_is_rejected(self):
        response = self.client.get('/api/takes/leaderboard/', {'period': 'year'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_period')

    def test_period_defaults_to_week(self):
        self.assertEqual(self.client.get('/api/takes/leaderboard/').json()['period'], 'week')


class ProgressTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='user', password='pw-123456')
        self.other = User.objects.create_user(username='other', password='pw-123456')

    def test_level_thresholds(self):
        self.assertEqual(total_xp(1), 0)
        self.assertEqual(total_xp(2), 100)
        self.assertEqual(total_xp(3), 250)
        self.assertEqual(total_xp(12), 3850)
        self.assertEqual(level_for_xp(0), 1)
        self.assertEqual(level_for_xp(99), 1)
        self.assertEqual(level_for_xp(100), 2)
        self.assertEqual(level_for_xp(249), 2)
        self.assertEqual(level_for_xp(250), 3)
        self.assertEqual(level_for_xp(3850), 12)
        self.assertEqual(level_for_xp(4499), 12)
        self.assertEqual(level_for_xp(4500), 13)

    def test_new_user_starts_at_level_one(self):
        progress = progress_for(self.user)

        self.assertEqual(
            (progress['level'], progress['xp'], progress['xp_into_level'], progress['xp_for_next_level']),
            (1, 0, 0, 100),
        )

    def test_xp_sums_reviews_comments_and_reactions(self):
        own = review(self.user, FILM)
        other_take = review(self.other, 'tt0000001')
        TakeComment.objects.create(take=other_take, author=self.user, body='Agreed')
        vote(own, self.other)

        progress = progress_for(self.user)

        self.assertEqual(progress['xp'], 20 + 5 + 2)
        self.assertEqual((progress['reviews'], progress['comments'], progress['reactions']), (1, 1, 1))
        self.assertEqual(progress['xp_into_level'], 27)
        self.assertEqual(progress['xp_for_next_level'], 100)

    def test_five_reviews_reach_level_two_exactly(self):
        for index in range(5):
            review(self.user, f'tt{index:07d}')

        progress = progress_for(self.user)

        self.assertEqual((progress['level'], progress['xp'], progress['xp_into_level']), (2, 100, 0))
        self.assertEqual(progress['xp_for_next_level'], 150)

    def test_self_votes_do_not_add_reactions(self):
        take = review(self.user, FILM)
        vote(take, self.user)
        vote(take, self.other, VoteKind.WELL_ARGUED)
        vote(take, self.other, VoteKind.CHANGED_MY_MIND)

        self.assertEqual(progress_for(self.user)['reactions'], 1)

    def test_film_critic_and_first_take_unlock_after_ten_reviews(self):
        for index in range(10):
            review(self.user, f'tt{index:07d}')

        progress = progress_for(self.user)

        film_critic = next(a for a in progress['achievements'] if a['key'] == 'film_critic')
        self.assertEqual(film_critic, {
            'key': 'film_critic', 'current': 10, 'target': 10, 'unlocked': True, 'available': True,
        })
        first_take = next(b for b in progress['badges'] if b['key'] == 'first_take')
        self.assertEqual(first_take, {'key': 'first_take', 'current': 10, 'target': 1, 'unlocked': True})

    def test_local_cinema_is_never_available_yet(self):
        local = next(a for a in progress_for(self.user)['achievements'] if a['key'] == 'local_cinema')

        self.assertEqual(local, {
            'key': 'local_cinema', 'current': 0, 'target': 20, 'unlocked': False, 'available': False,
        })

    def test_first_take_only_counts_the_earliest_review_on_a_film(self):
        start = timezone.now() - timedelta(days=2)
        review(self.other, FILM, at=start)
        review(self.user, FILM, at=start + timedelta(hours=1))
        review(self.user, 'tt0000001', at=start)
        review(self.user, '', at=start)

        first_take = next(b for b in progress_for(self.user)['badges'] if b['key'] == 'first_take')

        self.assertEqual(first_take['current'], 1)

    def test_well_argued_votes_drive_the_debater_frame(self):
        for index in range(50):
            take = review(self.user, f'tt{index:07d}')
            vote(take, self.other, VoteKind.WELL_ARGUED)

        progress = progress_for(self.user)

        debater = next(f for f in progress['frames'] if f['key'] == 'debater')
        explorer = next(f for f in progress['frames'] if f['key'] == 'explorer')
        self.assertEqual(debater, {'key': 'debater', 'current': 50, 'target': 50, 'unlocked': True})
        self.assertFalse(explorer['unlocked'])
        self.assertEqual(progress['badges'][0]['current'], 50)

    def test_bronze_frame_is_always_unlocked(self):
        frames = progress_for(self.user)['frames']

        self.assertEqual(frames[0], {'key': 'bronze', 'current': 0, 'target': 0, 'unlocked': True})
        self.assertEqual([frame['key'] for frame in frames],
                         ['bronze', 'explorer', 'debater', 'gold', 'legend'])

    def test_top_critic_badge_follows_the_weekly_top_three(self):
        take = review(self.user, FILM)
        vote(take, self.other)

        badges = {b['key']: b for b in progress_for(self.user)['badges']}

        self.assertEqual(badges['top_critic'], {'key': 'top_critic', 'current': 1, 'target': 1, 'unlocked': True})
