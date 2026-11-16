from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render


def index(request):
    """The FilmSage early-access landing page."""
    return render(request, 'landing/index.html')


def join(request):
    """Send a visitor who clicked "Join" to the FilmSage web app."""
    return HttpResponseRedirect(settings.FILMSAGE_APP_URL)
