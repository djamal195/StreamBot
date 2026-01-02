# On utilise l'image officielle de Playwright (contient déjà Chrome et Python)
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# On définit le dossier de travail
WORKDIR /app

# On copie tes fichiers dans le serveur
COPY . /app

# On installe Flask et Gunicorn (Playwright est déjà là grâce à l'image de base)
RUN pip install --no-cache-dir -r requirements.txt

# On installe juste le navigateur Chromium (les dépendances système sont déjà là)
RUN playwright install chromium

# On ouvre le port 5000
EXPOSE 5000

# La commande de démarrage
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--timeout", "120"]