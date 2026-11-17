from django.urls import path

from . import views

urlpatterns = [
    path('topics/', views.create_topic, name='takes_create_topic'),
    path('explore/', views.explore_takes, name='takes_explore'),
    path('friends/takes/', views.friend_takes, name='takes_friend_takes'),
    path('friends/stories/', views.friend_stories, name='takes_friend_stories'),
    path('me/takes/', views.my_takes, name='takes_my_takes'),
    path('top/', views.top_takes, name='takes_top'),
    path('topics/trending/', views.trending_topics, name='takes_trending_topics'),
    path('films/<str:film_id>/summary/', views.film_summary, name='takes_film_summary'),
    path('films/<str:film_id>/reaction/', views.set_reaction, name='takes_film_reaction'),
    path('films/<str:film_id>/takes/', views.film_takes, name='takes_film_takes'),
    path('films/<str:film_id>/friends/', views.friend_activity, name='takes_film_friends'),
    path('takes/<int:take_id>/', views.take_detail, name='takes_detail'),
    path('takes/<int:take_id>/report/', views.report_take, name='takes_report'),
    path('takes/<int:take_id>/share/', views.share_take, name='takes_share'),
    path('takes/<int:take_id>/votes/<str:kind>/', views.set_vote, name='takes_vote'),
    path('takes/<int:take_id>/comments/', views.take_comments, name='takes_comments'),
    path('takes/<int:take_id>/poll/', views.vote_poll, name='takes_poll_vote'),
    path('comments/<int:comment_id>/votes/<str:kind>/', views.set_comment_vote, name='takes_comment_vote'),
    path('leaderboard/', views.leaderboard, name='takes_leaderboard'),
    path('translate/', views.translate, name='takes_translate'),
]
