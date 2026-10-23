from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def inicio(request):
    return redirect("conciliacion:lista")


@login_required
def lista(request):
    return render(request, "conciliacion/lista.html", {"conciliaciones": []})
