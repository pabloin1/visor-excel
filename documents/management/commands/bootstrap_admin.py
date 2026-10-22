"""Create the first administrator from Render environment variables."""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea una vez el administrador de la demo usando variables de entorno."

    def handle(self, *args, **options):
        username = os.environ.get("VISOR_ADMIN_USERNAME", "").strip()
        password = os.environ.get("VISOR_ADMIN_PASSWORD", "")
        if not username or not password:
            raise CommandError("Defina VISOR_ADMIN_USERNAME y VISOR_ADMIN_PASSWORD para crear el administrador.")
        user_model = get_user_model()
        existing = user_model.objects.filter(username=username).first()
        if existing:
            if not existing.is_superuser or not existing.is_active:
                raise CommandError("El usuario indicado ya existe, pero no es un administrador activo.")
            self.stdout.write("El administrador ya existe; su contraseña no se modificó.")
            return
        user_model.objects.create_superuser(username=username, password=password)
        self.stdout.write(self.style.SUCCESS("Administrador creado."))
