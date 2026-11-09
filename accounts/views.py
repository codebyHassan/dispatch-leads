from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from crm.models import Lead, Template
from sync.models import Settings


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next") or "/"
            return redirect(next_url)
        error = "Invalid username or password."

    return render(request, "accounts/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def settings_view(request):
    cfg = Settings.get_solo()
    templates = Template.objects.all()

    if request.method == "POST":
        action = request.POST.get("action", "save_settings")

        if action == "save_settings":
            cfg.proxy_url = (request.POST.get("proxy_url") or "").strip()
            cfg.request_delay_ms = max(0, int(request.POST.get("request_delay_ms") or 300))
            cfg.timeout_s = max(3, int(request.POST.get("timeout_s") or 15))
            cfg.max_concurrency = max(1, int(request.POST.get("max_concurrency") or 2))
            cfg.qcmobile_webkey = (request.POST.get("qcmobile_webkey") or "").strip()
            cfg.socrata_app_token = (request.POST.get("socrata_app_token") or "").strip()
            cfg.freshness_hours = max(1, int(request.POST.get("freshness_hours") or 24))

            cfg.target_fleet_min = max(1, int(request.POST.get("target_fleet_min") or 1))
            cfg.target_fleet_max = max(cfg.target_fleet_min, int(request.POST.get("target_fleet_max") or 10))
            cfg.weight_new_mc = max(0, int(request.POST.get("weight_new_mc") or 25))
            cfg.weight_fleet_size = max(0, int(request.POST.get("weight_fleet_size") or 20))
            cfg.weight_phone = max(0, int(request.POST.get("weight_phone") or 20))
            cfg.weight_email = max(0, int(request.POST.get("weight_email") or 15))
            cfg.weight_insurance = max(0, int(request.POST.get("weight_insurance") or 10))
            cfg.weight_safety = max(0, int(request.POST.get("weight_safety") or 10))
            cfg.save()

            # Recalculate lead scores immediately so next page load reflects new weights
            for lead in Lead.objects.select_related("carrier").all():
                lead.refresh_score(cfg=cfg, save=True)

            messages.success(request, "Settings saved and lead scores recalculated.")
            return redirect("settings")

        elif action == "add_template":
            name = (request.POST.get("name") or "").strip()
            t_type = (request.POST.get("type") or "script").strip()
            body = (request.POST.get("body") or "").strip()
            if name and body:
                Template.objects.create(name=name, type=t_type, body=body)
                messages.success(request, f"Template '{name}' created.")
            return redirect("settings")

        elif action == "delete_template":
            t_id = request.POST.get("template_id")
            Template.objects.filter(pk=t_id).delete()
            messages.success(request, "Template removed.")
            return redirect("settings")

    return render(
        request,
        "accounts/settings.html",
        {
            "cfg": cfg,
            "templates": templates,
        },
    )
