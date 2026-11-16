"""ChantierVrai - suivi de chantier a distance (diaspora et grands chantiers).

Lancement :  python3 app.py   (puis ouvrir http://127.0.0.1:5000)
Rapports hebdomadaires (a planifier chaque jour, par exemple avec cron) :
    flask --app app rapports-hebdo
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import sqlite3
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import click

from flask import (Flask, Response, abort, flash, g, get_flashed_messages, got_request_exception, jsonify, redirect,
                   render_template, has_request_context, request, send_from_directory, session, url_for)
import numpy as np
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash

from services import env, run_async
from services import db as DB
from services import i18n as I18N
from services import glossary as GLOSS
from services.i18n import L, _
from services import materials as MAT
from services import media as MEDIA
from services import notify as NOTIFY
from werkzeug.exceptions import HTTPException
from services import payments as PAY
from services import billing as BILL
from services import guide_content as GUIDE
from services import quality as QUAL
from services import whatsapp as WA
from services import voice as VOICE
from services import finance as FIN
from services import land as LAND
from services import counting as COUNT
from services import offsite as OFFSITE
from services import kpi as KPI
from services import ops as OPS
from services import predict as PRED
from services import satellite as SAT
from services import security as SEC
from services import vision as VISION
from services import attestation as ATTEST
from services import calc as CALC
from services import geo as GEO
from services import ifc as IFC
from services import weather as WEATHER
from services import academy as ACAD
from services import assistant as ASSIST
from services import webhooks as HOOKS
from services import trust as TRUST

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.environ.get("CV_INSTANCE") or os.path.join(BASE_DIR, "instance")
UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads")
SAT_DIR = os.path.join(UPLOAD_DIR, "satellite")
DOC_DIR = os.path.join(UPLOAD_DIR, "documents")
INV_DIR = os.path.join(UPLOAD_DIR, "factures")
M3D_DIR = os.path.join(UPLOAD_DIR, "drone3d")
CIT_DIR = os.path.join(UPLOAD_DIR, "signalements")
DB_PATH = os.path.join(INSTANCE_DIR, "chantiervrai.db")

FRESH_MINUTES = 15          # une photo doit avoir ete prise il y a moins de 15 min
OFFLINE_HOURS = 72          # delai max d'une photo prise sans reseau puis envoyee au retour du reseau
COHERENCE_METERS = 300      # ecart max entre GPS de la photo et GPS du telephone
NEAR_DUP_BITS = 3           # ancienne empreinte (64 bits), gardee pour les preuves anterieures
NEAR_DUP_REFUSE = 0.10      # empreinte multiple : copie quasi certaine d'une preuve deja verifiee -> refus
NEAR_DUP_FLAG = 0.18        # zone de doute (meme endroit, recadrage ou ecran ?) -> acceptee mais signalee au proprietaire
DRONE_EXTRA_METERS = 500    # tolerance supplementaire pour les vues de drone
IMG_EXT = {"jpg", "jpeg", "png", "heic", "webp"}
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "odt", "ods", "jpg", "jpeg", "png", "dwg", "zip", "html", "txt"}
M3D_EXT = {"glb", "gltf"}
INVOICE_EXT = {"pdf", "jpg", "jpeg", "png", "webp"}

DEFAULT_STEPS = [
    ("Fondations", 3000000, 30),
    ("Soubassement", 2500000, 20),
    ("Dalle basse", 3500000, 20),
    ("Élévation des murs", 2500000, 35),
    ("Dalle haute", 2500000, 30),
    ("Toiture et finitions", 1500000, 45),
]
PUBLIC_STEPS = [  # grands chantiers : part du montant du marche, duree en jours
    ("Installation de chantier", 0.05, 20),
    ("Terrassements", 0.15, 45),
    ("Gros œuvre", 0.35, 120),
    ("Second œuvre", 0.20, 90),
    ("Finitions et équipements", 0.20, 60),
    ("Réception des travaux", 0.05, 15),
]
STATUS_LABELS = {
    "attente": "À venir",
    "en_cours": "En cours",
    "declare": "Déclarée terminée",
    "versement": "Validée, paiement en cours",
    "paye": "Validée et payée",
}
VALIDATED = ("versement", "paye")
DOC_CATEGORIES = ["DAO", "Contrat", "PV", "Plan", "Permis de construire", "Devis", "Contrôle technique", "Autre"]
ROLES = {"proprio": "Propriétaire / maître d'ouvrage", "chef": "Chef de chantier", "inspecteur": "Inspecteur indépendant",
         "fournisseur": "Fournisseur de matériaux", "pro": "Professionnel du BTP"}
ROLE_CHECK = "(role IN ('proprio', 'chef', 'inspecteur', 'fournisseur', 'pro'))"
PROFESSIONS = {"architecte": "Architecte", "ingenieur": "Ingénieur (structure, génie civil)",
               "bureau_controle": "Bureau de contrôle", "conducteur": "Conducteur de travaux",
               "entrepreneur": "Entrepreneur", "comptable": "Comptable"}
BUILDING_TYPES = {"maison": "Maison individuelle", "immeuble": "Immeuble (R+1 et plus)", "residence": "Résidence immobilière",
                  "ecole": "École ou université", "sante": "Hôpital ou centre de santé", "administratif": "Bâtiment administratif",
                  "infrastructure": "Route, pont ou infrastructure", "industriel": "Zone industrielle ou grand projet public"}
PARCEL_TOLERANCE = 30        # metres autour de la parcelle dessinee
INSP_STATUS = {"demandee": "Demandée", "acceptee": "Acceptée", "refusee": "Refusée", "realisee": "Réalisée",
               "annulee": "Annulée"}
VERDICTS = {"conforme": "Conforme", "reserves": "Conforme avec réserves", "non_conforme": "Non conforme"}
# Textes du script de capture (static/chef.js), traduits et transmis a la page
JS_STRINGS = [
    "Hors ligne : vos photos prises dans l'application sont gardées et partiront au retour du réseau.",
    "Connexion rétablie.", "Fermer", "Envoi…", "Qu'est-ce que c'est ?", "Envoyer la preuve",
    "Réseau trop faible : la photo est gardée sur le téléphone et partira automatiquement.",
    "Réseau trop faible : l'envoi n'a pas abouti. Réessayez dans un endroit mieux couvert.",
    "Avant votre première photo", "Position autorisée", "Caméra autorisée", "À autoriser", "Refusée",
    "Position refusée. Sur Android : touchez le cadenas à côté de l'adresse, puis Autorisations, puis Position. Sur iPhone : Réglages, Safari, Position.",
    "Caméra refusée. Sur Android : touchez le cadenas à côté de l'adresse, puis Autorisations, puis Caméra. Sur iPhone : Réglages, Safari, Caméra.",
    "Localisation non disponible sur ce téléphone.", "Position trouvée (précision %(n)s m).",
    "Position refusée : la preuve sera refusée. Autorisez la localisation.",
    "Caméra non disponible dans ce navigateur. Ouvrez ChantierVrai dans Chrome ou Safari à jour.",
    "Accès à la caméra refusé. Autorisez la caméra pour ce site dans les réglages du navigateur.",
    "Vidéo trop lourde : filmez moins longtemps.", "Vérification et envoi…",
    "Pas de réseau : seules les photos prises avec la caméra de l'application peuvent attendre le réseau.",
    "Pas de réseau : preuve gardée sur le téléphone, envoi automatique au retour du réseau.",
    "Impossible de garder la photo hors ligne sur ce téléphone.",
    "%(n)s preuve(s) en attente de réseau : envoi automatique dès le retour de la connexion.",
]

app = Flask(__name__, instance_path=INSTANCE_DIR)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("SESSION_COOKIE_SECURE") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
app.jinja_env.filters["fromjson"] = json.loads
app.jinja_env.globals["_"] = I18N._
app.jinja_env.globals["pl"] = I18N.pl


def asset(name):
    """Lien vers un fichier statique avec sa version : le téléphone reprend le nouveau fichier après une mise à jour."""
    try:
        v = int(os.path.getmtime(os.path.join(app.static_folder, name)))
    except OSError:
        v = 0
    return url_for("static", filename=name, v=v)


app.jinja_env.globals["asset"] = asset
app.jinja_env.filters["tr"] = lambda v: I18N.render(v, I18N.current_lang())
app.jinja_env.filters["reasons"] = lambda v: I18N.render_list(v, I18N.current_lang())
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('proprio', 'chef', 'inspecteur', 'fournisseur', 'pro')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    chef_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    address TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    radius INTEGER NOT NULL DEFAULT 100,
    invite_code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'attente',
    declared_at TEXT,
    paid_at TEXT,
    pay_ref TEXT
);
CREATE TABLE IF NOT EXISTS proofs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    photo_lat REAL, photo_lng REAL, photo_taken TEXT,
    device_lat REAL, device_lng REAL, device_acc REAL,
    distance INTEGER,
    ok INTEGER NOT NULL,
    reasons TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    user_id INTEGER REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('depot', 'versement')),
    amount INTEGER NOT NULL,
    provider TEXT NOT NULL,
    ref TEXT NOT NULL UNIQUE,
    provider_ref TEXT,
    payment_url TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sat_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    layer TEXT NOT NULL,
    filename TEXT NOT NULL,
    source TEXT NOT NULL,
    change_pct REAL,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, month, layer)
);
CREATE TABLE IF NOT EXISTS media3d (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('drone', 'modele3d', 'orthophoto')),
    filename TEXT NOT NULL,
    original_name TEXT,
    lat REAL, lng REAL, distance INTEGER, taken TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    step_id INTEGER REFERENCES steps(id),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT,
    sha256 TEXT,
    size INTEGER,
    is_public INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    material TEXT NOT NULL,
    unit TEXT,
    qty_planned REAL,
    unit_price_ref REAL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    user_id INTEGER REFERENCES users(id),
    filename TEXT NOT NULL,
    media_type TEXT,
    sha256 TEXT NOT NULL,
    supplier TEXT, number TEXT, inv_date TEXT, total REAL,
    status TEXT NOT NULL DEFAULT 'a_saisir',
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    material TEXT NOT NULL,
    raw_label TEXT,
    unit TEXT,
    qty REAL,
    unit_price REAL
);
CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    inspector_id INTEGER NOT NULL REFERENCES users(id),
    requested_by INTEGER NOT NULL REFERENCES users(id),
    wanted_date TEXT,
    message TEXT,
    fee INTEGER,
    status TEXT NOT NULL DEFAULT 'demandee',
    verdict TEXT,
    report TEXT,
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (key, created_at);
CREATE TABLE IF NOT EXISTS reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'coproprio',
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    opened_by INTEGER NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ouvert',
    resolution TEXT,
    resolved_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS dispute_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispute_id INTEGER NOT NULL REFERENCES disputes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    cycle TEXT NOT NULL DEFAULT 'mois',
    status TEXT NOT NULL,
    trial_end TEXT,
    period_start TEXT,
    period_end TEXT,
    cancel_at_end INTEGER NOT NULL DEFAULT 0,
    custom_price INTEGER,
    sites_limit INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS billing_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    cycle TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    amount_ht INTEGER NOT NULL,
    vat_rate REAL NOT NULL DEFAULT 0,
    vat INTEGER NOT NULL DEFAULT 0,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'a_payer',
    due_date TEXT NOT NULL,
    paid_at TEXT,
    method TEXT,
    reference TEXT,
    tx_ref TEXT,
    payment_url TEXT,
    reminders INTEGER NOT NULL DEFAULT 0,
    buyer TEXT,
    kind TEXT NOT NULL DEFAULT 'abonnement',
    inspection_request_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inspection_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    requested_by INTEGER NOT NULL REFERENCES users(id),
    wanted_date TEXT,
    message TEXT,
    price INTEGER NOT NULL,
    payout INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'a_payer',
    invoice_id INTEGER,
    inspection_id INTEGER,
    assigned_by INTEGER,
    assigned_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_by INTEGER,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS payment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    payer_id INTEGER REFERENCES users(id),
    payee_id INTEGER REFERENCES users(id),
    amount INTEGER NOT NULL,
    method TEXT NOT NULL,
    reference TEXT,
    paid_on TEXT,
    receipt TEXT,
    receipt_name TEXT,
    receipt_sha TEXT,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'declare',
    contest_note TEXT,
    created_at TEXT NOT NULL,
    answered_at TEXT,
    reminded_at TEXT
);
CREATE TABLE IF NOT EXISTS admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    target INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    device TEXT,
    session_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    push_token TEXT NOT NULL UNIQUE,
    platform TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestation_nonces (
    nonce TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    material TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    price INTEGER NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES steps(id),
    supplier_id INTEGER NOT NULL REFERENCES users(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    pay_mode TEXT NOT NULL DEFAULT 'sequestre',
    total INTEGER NOT NULL DEFAULT 0,
    received_total INTEGER,
    commission INTEGER,
    pay_ref TEXT,
    delivery_date TEXT,
    note TEXT,
    problem TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    received_at TEXT
);
CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id),
    material TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price INTEGER NOT NULL,
    qty_received REAL
);
CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    material TEXT NOT NULL,
    unit TEXT,
    qty REAL NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manuel',
    order_id INTEGER,
    note TEXT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    material TEXT NOT NULL,
    min_qty REAL NOT NULL,
    UNIQUE (project_id, material)
);
CREATE TABLE IF NOT EXISTS step_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL DEFAULT 'visuel',
    min_value REAL,
    unit TEXT,
    status TEXT NOT NULL DEFAULT 'a_faire',
    value REAL,
    note TEXT,
    doc_id INTEGER,
    checked_by INTEGER REFERENCES users(id),
    checked_at TEXT,
    made_optional INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    level TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bim_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    version INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT,
    summary TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bim_storeys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    storey TEXT NOT NULL,
    step_id INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    UNIQUE (project_id, storey)
);
CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT,
    token TEXT NOT NULL UNIQUE,
    min_value REAL,
    max_value REAL,
    last_value REAL,
    last_at TEXT,
    alarm INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    value REAL NOT NULL,
    measured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imagery_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    sat_image_id INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS academy_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    done_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contractor_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contractor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, author_id)
);
CREATE TABLE IF NOT EXISTS plan_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    doc_id INTEGER,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES zones(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'zone',
    storey TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pano_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    zone_id INTEGER REFERENCES zones(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    thumb TEXT,
    sha256 TEXT NOT NULL,
    feat TEXT,
    lat REAL,
    lng REAL,
    distance INTEGER,
    taken TEXT,
    ok INTEGER NOT NULL,
    reasons TEXT,
    change_pct REAL,
    ai_note TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    zone_id INTEGER REFERENCES zones(id) ON DELETE SET NULL,
    step_id INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    unit TEXT NOT NULL,
    qty_planned REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manuel',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    qty REAL NOT NULL,
    proof_id INTEGER,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'declare',
    user_id INTEGER NOT NULL REFERENCES users(id),
    validated_by INTEGER REFERENCES users(id),
    validated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL DEFAULT 'read',
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'en_attente',
    attempts INTEGER NOT NULL DEFAULT 0,
    response_code INTEGER,
    next_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    issued_at TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS signalements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT, phone TEXT,
    text TEXT NOT NULL,
    filename TEXT,
    lat REAL, lng REAL, distance INTEGER,
    ip TEXT,
    status TEXT NOT NULL DEFAULT 'nouveau',
    response TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id),
    zone_id INTEGER,
    ouvrage TEXT NOT NULL,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'photos',
    mode TEXT,
    lang TEXT,
    measures TEXT,
    measures_by INTEGER,
    measures_at TEXT,
    score INTEGER,
    judged INTEGER,
    summary TEXT,
    inspect INTEGER NOT NULL DEFAULT 0,
    same_place INTEGER,
    extras TEXT,
    ai_raw TEXT,
    error TEXT,
    previous_id INTEGER,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    analysed_at TEXT,
    analysed_photos INTEGER,
    closed_at TEXT,
    closed_by INTEGER
);
CREATE TABLE IF NOT EXISTS quality_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES quality_reviews(id) ON DELETE CASCADE,
    proof_id INTEGER NOT NULL REFERENCES proofs(id),
    shot TEXT NOT NULL,
    quality TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES quality_reviews(id) ON DELETE CASCADE,
    point TEXT NOT NULL,
    label TEXT,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    confidence REAL,
    proof_id INTEGER,
    zone TEXT,
    explanation TEXT,
    advice TEXT,
    question TEXT,
    measure_note TEXT,
    extra INTEGER NOT NULL DEFAULT 0,
    fixed TEXT,
    owner_status TEXT,
    owner_note TEXT,
    expert_status TEXT,
    expert_note TEXT,
    expert_by INTEGER,
    expert_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS quality_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES quality_reviews(id) ON DELETE CASCADE,
    point_id INTEGER,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wa_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL UNIQUE,
    user_id INTEGER,
    project_id INTEGER,
    awaiting TEXT,
    pending TEXT,
    loc_lat REAL, loc_lng REAL, loc_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS wa_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    phone TEXT NOT NULL,
    user_id INTEGER,
    project_id INTEGER,
    kind TEXT NOT NULL,
    body TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    step_id INTEGER,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    kind TEXT NOT NULL,
    filename TEXT,
    transcript TEXT,
    summary TEXT,
    category TEXT,
    urgent INTEGER NOT NULL DEFAULT 0,
    materials TEXT,
    status TEXT NOT NULL DEFAULT 'pret',
    error TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fin_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    monthly_income REAL,
    income_currency TEXT NOT NULL DEFAULT 'XOF',
    fx_rate REAL,
    other_charges REAL,
    employer TEXT,
    country TEXT,
    diaspora INTEGER NOT NULL DEFAULT 0,
    alert_key TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fin_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT,
    lender TEXT,
    amount INTEGER NOT NULL,
    expected_on TEXT,
    months INTEGER,
    rate REAL,
    deferral_months INTEGER,
    monthly_payment INTEGER,
    status TEXT NOT NULL DEFAULT 'prevue',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fin_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES fin_sources(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    received_on TEXT NOT NULL,
    note TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fin_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL,
    due_on TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fin_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT,
    filename TEXT NOT NULL,
    original_name TEXT,
    sha256 TEXT,
    size INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS land_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    doc_type TEXT,
    title_ref TEXT,
    holder_name TEXT,
    seller_name TEXT,
    area_declared REAL,
    bornes TEXT,
    checks TEXT,
    notes TEXT,
    updated_by INTEGER,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS land_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'nouvelle',
    result TEXT,
    handled_by INTEGER,
    created_at TEXT NOT NULL,
    handled_at TEXT
);
CREATE TABLE IF NOT EXISTS delivery_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    line_id INTEGER NOT NULL,
    ai_count REAL,
    ai_conf REAL,
    method TEXT,
    remark TEXT,
    photos INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    expected REAL,
    level TEXT,
    source TEXT,
    reading_id INTEGER,
    declared REAL,
    declared_by INTEGER,
    ai_count REAL,
    ai_conf REAL,
    ai_note TEXT,
    status TEXT NOT NULL DEFAULT 'a_faire',
    note TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS plan_item_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES plan_items(id) ON DELETE CASCADE,
    proof_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offsite_files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    sent_at TEXT
);
"""

MIGRATIONS = {
    "users": [("notify_email", "INTEGER NOT NULL DEFAULT 1"), ("notify_sms", "INTEGER NOT NULL DEFAULT 0"),
              ("notify_whatsapp", "INTEGER NOT NULL DEFAULT 1"), ("zone", "TEXT"), ("tarif", "INTEGER"),
              ("bio", "TEXT"), ("totp_secret", "TEXT"), ("totp_on", "INTEGER NOT NULL DEFAULT 0"),
              ("backup_codes", "TEXT"), ("verified", "INTEGER NOT NULL DEFAULT 0"),
              ("is_admin", "INTEGER NOT NULL DEFAULT 0"), ("blocked", "INTEGER NOT NULL DEFAULT 0"),
              ("terms_at", "TEXT"), ("session_version", "INTEGER NOT NULL DEFAULT 0"), ("deleted", "INTEGER NOT NULL DEFAULT 0"),
              ("lang", "TEXT"), ("profession", "TEXT"), ("verify_requested", "INTEGER NOT NULL DEFAULT 0"),
              ("company", "TEXT"), ("staff_role", "TEXT"),
              ("onboarding_hidden", "INTEGER NOT NULL DEFAULT 0"), ("advanced", "INTEGER NOT NULL DEFAULT 0"),
              ("supplier_terms_at", "TEXT")],
    "billing_invoices": [("kind", "TEXT NOT NULL DEFAULT 'abonnement'"), ("inspection_request_id", "INTEGER")],
    "disputes": [("stage", "TEXT NOT NULL DEFAULT 'echanges'"), ("respond_by", "TEXT"), ("decide_by", "TEXT"),
                 ("outcome", "TEXT"), ("amount", "INTEGER"), ("appeal_until", "TEXT"), ("appeal_text", "TEXT"),
                 ("appealed_by", "INTEGER"), ("appealed_at", "TEXT"), ("final_decision", "TEXT"), ("final_by", "INTEGER"),
                 ("final_at", "TEXT"), ("escalated", "INTEGER NOT NULL DEFAULT 0")],
    "admin_log": [("staff_role", "TEXT")],
    "projects": [("kind", "TEXT NOT NULL DEFAULT 'prive'"), ("is_public", "INTEGER NOT NULL DEFAULT 0"),
                 ("pay_mode", "TEXT NOT NULL DEFAULT 'manuel'"), ("start_date", "TEXT"), ("description", "TEXT"),
                 ("marche_ref", "TEXT"), ("ao_ref", "TEXT"), ("autorite", "TEXT"), ("attributaire", "TEXT"),
                 ("montant_marche", "INTEGER"), ("sigomap_url", "TEXT"),
                 ("require_app_capture", "INTEGER NOT NULL DEFAULT 0"), ("building_type", "TEXT"), ("levels", "INTEGER"),
                 ("surface_land", "REAL"), ("surface_floor", "REAL"), ("land_title", "TEXT"), ("land_ref", "TEXT"),
                 ("commune", "TEXT"), ("permit_ref", "TEXT"), ("parcel", "TEXT"),
                 ("auto_validate", "INTEGER NOT NULL DEFAULT 0"), ("require_inspection", "INTEGER NOT NULL DEFAULT 0")],
    "steps": [("planned_days", "INTEGER"), ("started_at", "TEXT"), ("checks_init", "INTEGER NOT NULL DEFAULT 0"),
              ("owner_reminders", "INTEGER NOT NULL DEFAULT 0"), ("auto_validated", "INTEGER NOT NULL DEFAULT 0"),
              ("insp_reminded", "INTEGER NOT NULL DEFAULT 0")],
    "proofs": [("kind", "TEXT NOT NULL DEFAULT 'photo'"), ("source", "TEXT NOT NULL DEFAULT 'chef'"),
               ("thumb", "TEXT"), ("duration", "REAL"), ("feat", "TEXT"), ("sim_dist", "INTEGER"),
               ("sim_color", "REAL"), ("ai_status", "TEXT"), ("ai_step", "TEXT"), ("ai_conf", "REAL"),
               ("ai_same_site", "INTEGER"), ("ai_construction", "INTEGER"), ("ai_note", "TEXT"),
               ("inspection_id", "INTEGER"), ("capture", "TEXT"), ("delayed_minutes", "INTEGER"),
               ("is_published", "INTEGER NOT NULL DEFAULT 0"), ("public_file", "TEXT"),
               ("attestation", "TEXT"), ("order_id", "INTEGER"), ("zone_id", "INTEGER"),
               ("sim_score", "REAL"), ("sim_ref", "INTEGER"), ("suspect", "INTEGER NOT NULL DEFAULT 0")],
    "signalements": [("hidden", "INTEGER NOT NULL DEFAULT 0"), ("reminded", "INTEGER NOT NULL DEFAULT 0"),
                     ("answered_at", "TEXT"), ("moderation_note", "TEXT")],
    "transactions": [("inspection_id", "INTEGER"), ("order_id", "INTEGER")],
    "inspections": [("paid", "INTEGER NOT NULL DEFAULT 0"), ("pay_ref", "TEXT"), ("sold", "INTEGER NOT NULL DEFAULT 0"),
                    ("payout_status", "TEXT"), ("payout_at", "TEXT"), ("request_id", "INTEGER")],
}


# --------------------------------------------------------------------------
# Base de donnees
# --------------------------------------------------------------------------
def connect():
    """Connexion a la base : SQLite par defaut, PostgreSQL si DATABASE_URL est defini."""
    return DB.connect(DB_PATH)


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    for d in (UPLOAD_DIR, SAT_DIR, DOC_DIR, INV_DIR, M3D_DIR, CIT_DIR):
        os.makedirs(d, exist_ok=True)
    if DB.is_pg():
        db = connect()
        db.executescript(DB.pg_schema(SCHEMA))
        for table, cols in MIGRATIONS.items():
            for name, decl in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {DB.pg_column_type(decl)}")
    else:
        db = sqlite3.connect(DB_PATH)
        db.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        # Anciennes bases : la liste des roles autorises s'allonge (inspecteur, fournisseur)
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()[0]
        if "'pro'" not in sql:
            new_sql = re.sub(r"role TEXT NOT NULL CHECK \(role IN \([^)]*\)\)", "role TEXT NOT NULL CHECK " + ROLE_CHECK, sql)
            new_sql = re.sub(r"^CREATE TABLE \"?users\"?", "CREATE TABLE users_new", new_sql)
            cols = ", ".join(r[1] for r in db.execute("PRAGMA table_info(users)"))
            db.commit()
            db.executescript(f"""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                {new_sql};
                INSERT INTO users_new ({cols}) SELECT {cols} FROM users;
                DROP TABLE users;
                ALTER TABLE users_new RENAME TO users;
                COMMIT;
                PRAGMA foreign_keys = ON;""")
    if DB.is_pg():
        db.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        db.execute("ALTER TABLE users ADD CONSTRAINT users_role_check CHECK " + ROLE_CHECK)
    # Anciennes bases : un administrateur sans role equipe devient super-admin
    db.execute("UPDATE users SET staff_role = 'super' WHERE is_admin = 1 AND staff_role IS NULL")
    db.execute("UPDATE steps SET started_at = (SELECT created_at FROM projects WHERE projects.id = steps.project_id) "
               "WHERE status = 'en_cours' AND started_at IS NULL")
    db.commit()
    db.close()
    make_icons()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(project_id, text, db=None, user_id=None):
    (db or get_db()).execute(
        "INSERT INTO activity (project_id, user_id, text, created_at) VALUES (?,?,?,?)",
        (project_id, user_id if user_id is not None else session.get("user_id"), I18N.store(text), now_iso()))


# --------------------------------------------------------------------------
# Notifications (application + WhatsApp / SMS / e-mail)
# --------------------------------------------------------------------------
def public_url(path):
    base = env("PUBLIC_URL")
    return (base.rstrip("/") + path) if base else None


def notify(project_id, user_ids, title, body, path=None, important=False, db=None):
    """Enregistre la notification dans l'application et, si important, l'envoie
    sur les canaux choisis par chaque utilisateur."""
    db = db or get_db()
    created = []
    for uid in {u for u in user_ids if u}:
        user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            continue
        db.execute("INSERT INTO notifications (user_id, project_id, channel, title, body, link, status, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?)", (uid, project_id, "app", I18N.store(title), I18N.store(body), path,
                                                "envoye", now_iso()))
        if not important:
            continue
        has_device = db.execute("SELECT 1 FROM devices WHERE user_id = ?", (uid,)).fetchone()
        for ch in ("push", "whatsapp", "sms", "email"):
            if ch == "push" and not has_device:
                continue
            if ch == "push" or (user[f"notify_{ch}"] and (ch == "email" or user["phone"])):
                cur = db.execute("INSERT INTO notifications (user_id, project_id, channel, title, body, link, status, "
                                 "is_read, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                                 (uid, project_id, ch, I18N.store(title), I18N.store(body), path, "en_attente", now_iso()))
                created.append(cur.lastrowid)
    if created:
        db.commit()
        run_async(_send_pending, created)


def _send_pending(ids):
    db = connect()
    try:
        for nid in ids:
            n = db.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
            user = db.execute("SELECT * FROM users WHERE id = ?", (n["user_id"],)).fetchone()
            lang = user["lang"] or I18N.DEFAULT
            title, body = I18N.render(n["title"], lang), I18N.render(n["body"], lang)
            if n["channel"] == "push":
                tokens = [r[0] for r in db.execute("SELECT push_token FROM devices WHERE user_id = ?", (user["id"],))]
                status, detail = NOTIFY.send_push(tokens, title, body, {"link": n["link"], "project_id": n["project_id"]})
            else:
                status, detail = NOTIFY.send(n["channel"], user, title, body,
                                             public_url(n["link"]) if n["link"] else None)
            db.execute("UPDATE notifications SET status = ?, detail = ? WHERE id = ?", (status, detail, nid))
            db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# Securite : connexion, jeton anti-CSRF, acces aux chantiers
# --------------------------------------------------------------------------
def bearer_user():
    """Utilisateur de l'application mobile (en-tete Authorization: Bearer <jeton>)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    db = get_db()
    row = db.execute("SELECT * FROM api_tokens WHERE token_hash = ? AND revoked = 0",
                     (hashlib.sha256(auth[7:].strip().encode()).hexdigest(),)).fetchone()
    if row is None:
        return None
    u = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if u is None or u["blocked"] or u["deleted"] or u["session_version"] != row["session_version"]:
        return None
    if not row["last_used"] or row["last_used"][:13] != now_iso()[:13]:      # au plus une ecriture par heure
        db.execute("UPDATE api_tokens SET last_used = ? WHERE id = ?", (now_iso(), row["id"]))
        db.commit()
    g.api_token_id = row["id"]
    return u


def current_user():
    if "user" in g:
        return g.user
    if request.headers.get("Authorization", "").startswith("Bearer "):
        g.user = bearer_user()
        return g.user
    uid = session.get("user_id")
    u = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
    # compte bloque, supprime, ou mot de passe change depuis la connexion : session invalide
    if u is not None and (u["blocked"] or u["deleted"] or session.get("sv", 0) != u["session_version"]):
        session.pop("user_id", None)
        u = None
    g.user = u
    return u


def start_session(user):
    chosen = session.get("lang")             # langue choisie avant la connexion : on la garde
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["sv"] = user["session_version"]
    if chosen in I18N.LANGS:
        session["lang"] = chosen
        if user["lang"] != chosen:
            get_db().execute("UPDATE users SET lang = ? WHERE id = ?", (chosen, user["id"]))
            get_db().commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login", next=request.path))
            if u["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return deco


# --------------------------------------------------------------------------
# Equipe ChantierVrai : roles internes, distincts des comptes clients
# --------------------------------------------------------------------------
STAFF_ROLES = {"super": "Super-admin (fondateur)", "verification": "Vérification",
               "support": "Support, litiges et modération", "commercial": "Commercial", "finance": "Finance"}
STAFF_ROLE_HELP = {
    "super": "Tout, y compris l'équipe, la récupération des comptes et le journal.",
    "verification": "Valide inspecteurs, fournisseurs, entrepreneurs et bureaux d'études ; attribue les inspections. Aucun montant.",
    "support": "Litiges, modération du portail citoyen, blocage des comptes. Ouvre un chantier seulement pour un dossier.",
    "commercial": "Activité des achats de matériaux et devis d'images satellite. Ne voit pas les commissions.",
    "finance": "Séquestre, commissions, volumes d'achats et images satellite. Ne valide pas les vérifications.",
}
STAFF_PERMS = {
    "super": {"verify", "disputes", "moderation", "accounts", "recovery", "projects", "commerce", "money", "imagery",
              "team", "journal", "platform", "inspections"},
    "verification": {"verify", "inspections"},
    "support": {"disputes", "moderation", "accounts", "projects", "inspections"},
    "commercial": {"commerce", "imagery"},
    "finance": {"commerce", "money", "imagery"},
}


def staff_role(u):
    if not u or not u["is_admin"]:
        return None
    return u["staff_role"] if u["staff_role"] in STAFF_ROLES else "super"


def staff_2fa_required():
    """2FA obligatoire pour l'equipe. Desactivable seulement en test (STAFF_2FA = False)."""
    v = app.config.get("STAFF_2FA")
    return (not app.config.get("TESTING")) if v is None else bool(v)


def staff_ready(u):
    return bool(staff_role(u)) and (bool(u["totp_on"]) or not staff_2fa_required())


def can(perm, u=None):
    u = u if u is not None else current_user()
    return staff_ready(u) and perm in STAFF_PERMS[staff_role(u)]


def staff_log(db, me, action, target=None):
    db.execute("INSERT INTO admin_log (admin_id, action, target, created_at, staff_role) VALUES (?,?,?,?,?)",
               (me["id"], action, target, now_iso(), staff_role(me)))
    app.logger.info("equipe %s (%s) : %s sur %s", me["email"], staff_role(me), action, target)


def admin_required(view=None, perm=None):
    """Reserve une page a l'equipe ChantierVrai ; perm restreint a un role. 2FA exigee."""
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login", next=request.path))
            if not staff_role(u):
                abort(403)
            if not staff_ready(u):
                flash(_("Activez la double authentification pour accéder à l'administration."), "error")
                return redirect(url_for("security"))
            if perm and not can(perm, u):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return deco(view) if view else deco


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


CSRF_EXEMPT = {"run_task_route", "cinetpay_notify", "whatsapp_incoming"}


@app.before_request
def check_csrf():
    # L'application mobile s'authentifie par jeton (en-tete Authorization) : pas de cookie, pas de risque CSRF
    if request.headers.get("Authorization", "").startswith("Bearer ") or request.path.startswith("/api/"):
        return
    if request.method == "POST" and request.endpoint not in CSRF_EXEMPT:
        sent = request.form.get("csrf")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, _('Jeton de sécurité invalide. Rechargez la page.'))


@app.before_request
def choose_language():
    """Langue : choix explicite (?lang=en), puis compte, puis session, puis navigateur."""
    want = request.args.get("lang")
    u = current_user()
    if want in I18N.LANGS:
        session["lang"] = want
        if u and u["lang"] != want:
            get_db().execute("UPDATE users SET lang = ? WHERE id = ?", (want, u["id"]))
            get_db().commit()
            g.pop("user", None)
    g.lang = want if want in I18N.LANGS else ((u["lang"] if u and u["lang"] else None) or session.get("lang")
                                              or I18N.best_match(request.headers.get("Accept-Language")))


@app.after_request
def fetch_redirects(resp):
    """Envoi d'une preuve par chef.js (fetch, pour survivre à un réseau faible) : la redirection est rendue
    en JSON, le message de confirmation reste en session et s'affiche sur la page suivante."""
    if request.headers.get("X-CV-Fetch") == "1" and resp.status_code in (301, 302, 303) and resp.location:
        out = jsonify(redirect=resp.location)
        for c in resp.headers.getlist("Set-Cookie"):
            out.headers.add("Set-Cookie", c)
        return out
    return resp


@app.after_request
def security_headers(resp):
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "geolocation=(self), camera=(self), microphone=(self)")
    h.setdefault("Content-Security-Policy",
                 "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
                 "style-src 'self' 'unsafe-inline' https://unpkg.com; font-src 'self'; "
                 "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://server.arcgisonline.com https://unpkg.com; "
                 "media-src 'self' blob:; connect-src 'self' blob: data: https://unpkg.com; worker-src 'self' blob:; "
                 "frame-ancestors 'self'; form-action 'self' https://checkout.cinetpay.com; base-uri 'self'")
    if app.config.get("SESSION_COOKIE_SECURE"):
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint and request.endpoint not in ("static", "manifest", "service_worker") and current_user():
        h.setdefault("Cache-Control", "private, no-store")
    return resp


def format_dt(iso):
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime("%d/%m/%Y %H:%M") + (" UTC" if d.tzinfo else "")
    except ValueError:
        return iso


def format_d(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d/%m/%Y")


def tr(d):
    """Dictionnaire de libelles traduits dans la langue de la requete."""
    return {k: _(v) for k, v in d.items()}


def sub_banner(me):
    """Bandeau d'abonnement pour le proprietaire : fin d'essai proche, retard de paiement, suspension."""
    if not me or me["role"] != "proprio" or not billing_enforced() or request.endpoint in ("subscription", "billing_invoice"):
        return None
    try:
        v = sub_view(get_db(), me)
    except Exception:
        return None
    if v["status"] == "essai" and v["days_left"] is not None and v["days_left"] <= 7:
        return ("warn", _("Votre essai gratuit se termine dans %(n)s jour(s).", n=v["days_left"]))
    if v["status"] == "essai_fini":
        return ("bad", _("Votre essai gratuit est terminé. Vos chantiers restent accessibles ; choisissez une offre pour en créer d'autres."))
    if v["status"] == "impaye":
        return ("warn", _("Facture en retard : réglez-la pour éviter la suspension."))
    if v["status"] == "suspendu":
        return ("bad", _("Abonnement suspendu pour impayé : création de chantiers et options payantes bloquées."))
    return None


def ago(iso):
    """« il y a 2 h », « hier », « il y a 3 j » : fraîcheur d'une photo ou d'un événement."""
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    m = int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    if m < 1:
        return _("à l'instant")
    if m < 60:
        return _("il y a %(n)s min", n=m)
    if m < 24 * 60:
        return _("il y a %(n)s h", n=m // 60)
    if m < 48 * 60:
        return _("hier")
    return _("il y a %(n)s j", n=m // 1440)


HOME_ENDPOINTS = ("home", "project", "new_project", "reports", "report", "invoice", "dispute")


def app_nav(me):
    """Menu de l'application selon le rôle : 4 onglets en bas sur téléphone (+ « Plus »), le reste dans le panneau.
    Chaque entrée : (clé, libellé, adresse, icône, points d'entrée qui l'allument)."""
    role = me["role"]
    home_label = {"fournisseur": _("Commandes"), "inspecteur": _("Missions")}.get(role, _("Chantiers"))
    items = {
        "home": (home_label, url_for("home"), "home", HOME_ENDPOINTS),
        "payments": (_("Paiements"), url_for("payments_received"), "wallet", ("payments_received",)),
        "map": (_("Carte"), url_for("map_view"), "map", ("map_view",)),
        "assistant": (_("Assistant"), url_for("assistant"), "chat", ("assistant",)),
        "academy": (_("Académie"), url_for("academy"), "book", ("academy", "academy_course", "calculator_public")),
        "contractors": (_("Entrepreneurs"), url_for("contractors"), "people", ("contractors", "contractor")),
        "help": (_("Aide"), url_for("help_page"), "help", ("help_page",)),
        "account": (_("Mon compte"), url_for("account"), "user", ("account", "security", "subscription")),
        "alerts": (_("Alertes"), url_for("notifications"), "bell", ("notifications",)),
    }
    primary = {"proprio": ["home", "map", "assistant", "help"], "pro": ["home", "payments", "assistant", "help"],
               "chef": ["home", "payments", "assistant", "help"], "inspecteur": ["home", "payments", "academy", "help"],
               "fournisseur": ["home", "payments", "help"]}.get(role, ["home", "help"])
    allowed = {"proprio": ["home", "map", "academy", "assistant", "contractors"], "pro": ["home", "payments", "map", "academy", "assistant"],
               "chef": ["home", "payments", "academy", "assistant"], "inspecteur": ["home", "payments", "academy"],
               "fournisseur": ["home", "payments"]}.get(role, ["home"])
    order = ["home", "payments", "map", "assistant", "academy", "contractors", "help", "alerts", "account"]
    full = [k for k in order if k in allowed or k in ("help", "alerts", "account")]
    more = [k for k in full if k not in primary and k != "alerts"]
    mk = lambda k: dict(key=k, label=items[k][0], url=items[k][1], icon=items[k][2], eps=items[k][3])
    admin = []
    if me["is_admin"]:
        admin.append(dict(key="admin", label=_("Administration"), url=url_for("admin"), icon="shield", eps=("admin",)))
        if can("money"):
            admin.append(dict(key="pilotage", label=_("Pilotage"), url=url_for("pilotage"), icon="chart", eps=("pilotage",)))
    return {"primary": [mk(k) for k in primary], "more": [mk(k) for k in more] + admin,
            "side": [mk(k) for k in full] + admin}


@app.context_processor
def inject_globals():
    me = current_user()
    unread = 0
    if me:
        unread = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' "
                                  "AND is_read = 0", (me["id"],)).fetchone()[0]
    return {"csrf_token": csrf_token, "me": me, "STATUS": tr(STATUS_LABELS), "ROLES": tr(ROLES),
            "lang": I18N.current_lang(), "LANGS": I18N.LANGS, "JS_T": {k: _(k) for k in JS_STRINGS},
            "GLOSS": GLOSS.for_lang(I18N.current_lang()),
            "fcfa": lambda n: f"{int(round(n or 0)):,}".replace(",", " "),
            "dt": format_dt, "d": format_d, "unread": unread, "INSP_STATUS": tr(INSP_STATUS), "VERDICTS": tr(VERDICTS),
            "ai_on": VISION.ai_enabled(), "sat_on": SAT.configured(), "SAT_LAYERS": tr(SAT.LAYERS),
            "DOC_CATEGORIES": DOC_CATEGORIES, "MATERIALS": list(MAT.CATALOG), "ORDER_STATUS": tr(ORDER_STATUS), "MEMBER_ROLES": tr(MEMBER_ROLES), "PROFESSIONS": tr(PROFESSIONS), "IMAGERY_PROVIDERS": IMAGERY_PROVIDERS,
            "IMAGERY_STATUS": tr(IMAGERY_STATUS), "sigomap_portal": env("SIGOMAP_URL"),
            "can": can, "STAFF_ROLES": tr(STAFF_ROLES), "my_staff_role": staff_role(me),
            "escrow_on": escrow_enabled(), "PAY_MODES": tr(PAY_MODES), "advanced": g.get("advanced", True),
            "sub_banner": sub_banner(me), "SIG_STATUS": tr(SIG_STATUS), "DSTAGES": tr(DISPUTE_STAGES),
            "AUTO_VALIDATE_DAYS": auto_validate_days(), "auto_validate_on": auto_validate_on(),
            "is_critical": is_critical, "NAV": app_nav(me) if me else None, "ago": ago, "compact": compact}


def project_role(p, user=None):
    user = user or current_user()
    if not user:
        return None
    if user["id"] == p["owner_id"]:
        return "owner"
    if user["id"] == p["chef_id"]:
        return "chef"
    db = get_db()
    m = db.execute("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?", (p["id"], user["id"])).fetchone()
    if m:
        g.member_role = m["role"]
        return MEMBER_ACCESS.get(m["role"], "intervenant")
    if user["role"] == "inspecteur" and db.execute(
            "SELECT 1 FROM inspections WHERE project_id = ? AND inspector_id = ? AND status IN ('acceptee','realisee')",
            (p["id"], user["id"])).fetchone():
        return "inspecteur"
    if can("projects", user):
        return "admin"
    return None


def load_project(project_id, roles=("owner", "chef", "inspecteur")):
    """Charge un chantier et verifie que l'utilisateur y a acces."""
    p = get_db().execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if p is None:
        abort(404)
    role = project_role(p)
    if role not in roles:
        abort(403)
    g.project_role = role
    return p


def is_owner(p):
    return project_role(p) == "owner"


def owners_of(p, db=None):
    """Proprietaire principal et co-proprietaires d'un chantier."""
    db = db or get_db()
    return [p["owner_id"]] + [r[0] for r in db.execute("SELECT user_id FROM project_members WHERE project_id = ? "
                                                      "AND role IN ('coproprio', 'finance')", (p["id"],))]


# --------------------------------------------------------------------------
# Outils : distance, EXIF, fichiers
# --------------------------------------------------------------------------
def haversine(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _ratio(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float(x[0]) / float(x[1]) if x[1] else 0.0


def read_exif(img):
    """Retourne (lat, lng, date_prise_naive) lus dans la photo, ou None."""
    lat = lng = taken = None
    try:
        exif = img.getexif()
        gps = exif.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            la = sum(_ratio(v) / d for v, d in zip(gps[2], (1, 60, 3600)))
            lo = sum(_ratio(v) / d for v, d in zip(gps[4], (1, 60, 3600)))
            if gps.get(1) == "S":
                la = -la
            if gps.get(3) == "W":
                lo = -lo
            if la or lo:
                lat, lng = la, lo
        raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
        if raw:
            taken = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except Exception:  # photo sans EXIF ou EXIF illisible
        pass
    return lat, lng, taken


def to_float(value):
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def to_int(value, default=0):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else default


def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""


def plain(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def save_image(img, folder, max_side=1600, prefix=""):
    name = f"{prefix}{secrets.token_hex(12)}.jpg"
    im = ImageOps.exif_transpose(img).convert("RGB")
    im.thumbnail((max_side, max_side))
    im.save(os.path.join(folder, name), "JPEG", quality=82)
    return name


# --------------------------------------------------------------------------
# Statistiques, prediction, alertes
# --------------------------------------------------------------------------
def escrow(project_id, db=None):
    db = db or get_db()
    rows = db.execute("SELECT kind, status, SUM(amount) AS s FROM transactions WHERE project_id = ? "
                      "GROUP BY kind, status", (project_id,)).fetchall()
    tot = {(r["kind"], r["status"]): r["s"] or 0 for r in rows}
    deposited = tot.get(("depot", "reussi"), 0)
    released = tot.get(("versement", "reussi"), 0)
    pending_out = tot.get(("versement", "en_attente"), 0)
    return {"deposited": deposited, "released": released, "pending_out": pending_out,
            "balance": deposited - released - pending_out,
            "pending_in": tot.get(("depot", "en_attente"), 0)}


def project_stats(project_id, db=None):
    db = db or get_db()
    p = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    total = sum(s["amount"] for s in steps)
    validated = sum(s["amount"] for s in steps if s["status"] in VALIDATED)
    paid = sum(s["amount"] for s in steps if s["status"] == "paye")
    declared = sum(s["amount"] for s in steps if s["status"] in VALIDATED + ("declare",))
    current = next((s for s in steps if s["status"] in ("en_cours", "declare")), None)
    last = db.execute("SELECT created_at FROM proofs WHERE project_id = ? AND source = 'chef' ORDER BY id DESC LIMIT 1",
                      (project_id,)).fetchone()
    ref_date = last["created_at"] if last else (p["created_at"] if p else None)
    days_silent = (datetime.now(timezone.utc) - datetime.fromisoformat(ref_date)).days if ref_date else None
    esc = escrow(project_id, db)
    sequestre = p is not None and p["pay_mode"] == "sequestre"
    counts = db.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS bad FROM proofs WHERE project_id = ?",
                        (project_id,)).fetchone()
    return {
        "steps": steps, "total": total, "paid": esc["released"] if sequestre else paid,
        "locked": esc["balance"] if sequestre else total - paid,
        "to_deposit": max(total - esc["deposited"] - esc["pending_in"], 0) if sequestre else 0,
        "escrow": esc, "sequestre": sequestre, "suivi": p is not None and p["pay_mode"] == "suivi",
        "awaiting_pay": sum(s["amount"] for s in steps if s["status"] == "versement") if not sequestre else 0,
        "verified_pct": round(validated * 100 / total) if total else 0,
        "declared_pct": round(declared * 100 / total) if total else 0,
        "current": current,
        "to_validate": sum(1 for s in steps if s["status"] == "declare"),
        "refused": counts["bad"] or 0, "proofs_total": counts["n"] or 0,
        "days_silent": days_silent if last else None,
        "silent_since_start": days_silent if not last else None,
    }


def project_prediction(p, s, db=None):
    db = db or get_db()
    nc = db.execute("SELECT COUNT(*) FROM inspections i JOIN steps st ON st.id = i.step_id WHERE i.project_id = ? "
                    "AND i.verdict = 'non_conforme' AND st.status NOT IN ('paye','versement')",
                    (p["id"],)).fetchone()[0]
    silent = s["days_silent"] if s["days_silent"] is not None else s["silent_since_start"]
    return PRED.predict(p, s["steps"], silent, s["refused"], s["proofs_total"], nc)


def project_alerts(p, s, pred, db=None):
    """Liste d'alertes (texte, lien d'onglet)."""
    db = db or get_db()
    out = []
    if s["to_validate"]:
        out.append((_('%(to_validate)s étape déclarée terminée à valider', to_validate=s['to_validate']), 'etapes',
                    _('Vérifiez les preuves avant de payer.')))
    if s["refused"]:
        out.append((_('%(refused)s preuve(s) refusée(s)', refused=s['refused']), 'preuves', _('Hors zone, ancienne, en double ou retouchée.')))
    if s["days_silent"] is not None and s["days_silent"] >= 7:
        out.append((_('Aucune preuve depuis %(days_silent)s jours', days_silent=s['days_silent']), None, _("Le chantier est peut-être à l'arrêt.")))
    if pred and not pred["done"] and pred["delay"] > 7:
        out.append((_('Retard prévu : %(delay)s jours', delay=pred['delay']), 'etapes',
                    _('Fin estimée le %(format_d)s au lieu du %(format_d2)s.', format_d=format_d(pred['predicted_end']), format_d2=format_d(pred['planned_end']))))
    ai_bad = db.execute("SELECT COUNT(*) FROM proofs WHERE project_id = ? AND ok = 1 AND "
                        "(ai_same_site = 0 OR ai_construction = 0)", (p["id"],)).fetchone()[0]
    if ai_bad:
        out.append((_("%(ai_bad)s photo(s) douteuse(s) selon l'IA", ai_bad=ai_bad), 'preuves',
                    _('Autre bâtiment ou pas un chantier : regardez-les avant de payer.')))
    plans = db.execute("SELECT * FROM materials_plan WHERE project_id = ?", (p["id"],)).fetchall()
    lines = db.execute("SELECT l.* FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id WHERE i.project_id = ?",
                       (p["id"],)).fetchall()
    _t, mat_alerts = MAT.compare(plans, lines, s["steps"])
    dups = db.execute("SELECT COUNT(*) FROM invoices WHERE project_id = ? AND status = 'doublon'",
                      (p["id"],)).fetchone()[0]
    _st, stock_alerts = stock_summary(db, p["id"])
    if stock_alerts:
        out.append((_('%(v)s alerte(s) sur le stock', v=len(stock_alerts)), 'dossier', stock_alerts[0]))
    overdue = db.execute("SELECT COUNT(*) FROM step_checks c JOIN steps st ON st.id = c.step_id WHERE c.project_id = ? "
                         "AND c.required = 1 AND c.status != 'conforme' AND st.status = 'declare'", (p["id"],)).fetchone()[0]
    nc = db.execute("SELECT COUNT(*) FROM step_checks WHERE project_id = ? AND status = 'non_conforme'", (p["id"],)).fetchone()[0]
    if overdue:
        out.append((_('%(v)s contrôle(s) obligatoire(s) à faire avant de payer', v=overdue), 'etapes',
                    _('Un contrôleur habilité doit passer sur le chantier.')))
    if nc:
        out.append((_('%(v)s non-conformité(s) relevée(s)', v=nc), 'etapes', _('Faites corriger puis contrôler à nouveau.')))
    if mat_alerts or dups:
        out.append((_('%(v)s alerte(s) sur les matériaux', v=len(mat_alerts) + dups), 'dossier',
                    (mat_alerts[0] if mat_alerts else _('Facture en double'))))
    sat = db.execute("SELECT * FROM sat_images WHERE project_id = ? AND layer = 'optique' AND change_pct IS NOT NULL "
                     "ORDER BY month DESC LIMIT 1", (p["id"],)).fetchone()
    if sat and sat["change_pct"] < 2:
        since = sat["month"] + "-01"
        moved = db.execute("SELECT COUNT(*) FROM steps WHERE project_id = ? AND declared_at >= ?",
                           (p["id"], since)).fetchone()[0]
        if moved:
            out.append((_('Le satellite ne voit presque aucun changement'), 'vues',
                        _('Alors que %(moved)s étape(s) ont été déclarées depuis %(month)s.', moved=moved, month=sat['month'])))
    nc = db.execute("SELECT COUNT(*) FROM inspections WHERE project_id = ? AND verdict = 'non_conforme' "
                    "AND done_at >= ?", (p["id"], (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
                                         )).fetchone()[0]
    if nc:
        out.append((_('Inspection non conforme'), 'dossier', _("Lisez le rapport de l'inspecteur.")))
    nd = db.execute("SELECT COUNT(*) FROM disputes WHERE project_id = ? AND status = 'ouvert'", (p["id"],)).fetchone()[0]
    if nd:
        out.append((_('%(nd)s litige(s) en cours', nd=nd), 'dossier', _('Suivez la médiation dans le dossier du chantier.')))
    sig = db.execute("SELECT COUNT(*) FROM signalements WHERE project_id = ? AND status = 'nouveau'",
                     (p["id"],)).fetchone()[0]
    if sig:
        out.append((_('%(sig)s signalement(s) citoyen(s) à traiter', sig=sig), 'dossier', _('Reçu(s) sur le portail public.')))
    return out


# --------------------------------------------------------------------------
# Comptes
# --------------------------------------------------------------------------
LOGIN_MAX_PER_EMAIL = 5      # essais rates par compte sur 15 minutes
LOGIN_MAX_PER_IP = 30        # essais rates par adresse IP sur 15 minutes


def client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]).strip()


def too_many_attempts(email):
    since = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    db = get_db()
    n_mail = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key = ? AND created_at >= ?",
                        ("e:" + email, since)).fetchone()[0]
    n_ip = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key = ? AND created_at >= ?",
                      ("ip:" + client_ip(), since)).fetchone()[0]
    return n_mail >= LOGIN_MAX_PER_EMAIL or n_ip >= LOGIN_MAX_PER_IP


def record_failure(email):
    db = get_db()
    for key in ("e:" + email, "ip:" + client_ip()):
        db.execute("INSERT INTO login_attempts (key, created_at) VALUES (?, ?)", (key, now_iso()))
    db.execute("DELETE FROM login_attempts WHERE created_at < ?",
               ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
    db.commit()


@app.route("/inscription", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        password, role = f.get("password", ""), f.get("role")
        problem = SEC.password_problem(password, email)
        profession = f.get("profession") if role == "pro" else None
        if role == "pro" and profession not in PROFESSIONS:
            flash(_("Choisissez votre métier."), "error")
            return render_template("register.html")
        if not name or "@" not in email or role not in ROLES:
            flash(_('Renseignez nom, e-mail et rôle.'), "error")
        elif problem:
            flash(problem, "error")
        elif role == "fournisseur" and not f.get("supplier_terms"):
            flash(_("Acceptez les conditions fournisseur, dont la commission ChantierVrai."), "error")
        elif not f.get("terms"):
            flash(_("Acceptez les conditions d'utilisation et la politique de confidentialité."), "error")
        else:
            try:
                db = get_db()
                admins = [e.strip().lower() for e in env("ADMIN_EMAILS").split(",") if e.strip()]
                cur = db.execute(
                    "INSERT INTO users (name, email, phone, password_hash, role, created_at, zone, tarif, bio, terms_at, "
                    "is_admin, lang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, email, f.get("phone", "").strip(), generate_password_hash(password), role, now_iso(),
                     f.get("zone", "").strip()[:80] or None, to_int(f.get("tarif"), None),
                     ("\n".join(x for x in (f.get("company", "").strip()[:120], f.get("bio", "").strip()) if x)[:600]
                      or None), now_iso(), 1 if email in admins else 0, g.lang))
                if profession:
                    db.execute("UPDATE users SET profession = ? WHERE id = ?", (profession, cur.lastrowid))
                if role == "fournisseur":
                    db.execute("UPDATE users SET supplier_terms_at = ? WHERE id = ?", (now_iso(), cur.lastrowid))
                db.commit()
                start_session(db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())
                if role == "pro":
                    flash(_("Compte créé. Donnez votre e-mail au propriétaire du chantier : il vous ajoute avec votre rôle (architecte, ingénieur, conducteur de travaux…).")
                          + (" " + _("Ingénieurs et bureaux de contrôle : vos qualifications sont vérifiées avant de pouvoir valider des contrôles.")
                             if profession in ("ingenieur", "bureau_controle") else ""), "ok")
                    return redirect(url_for("home"))
                if role == "fournisseur":
                    flash(_("Compte créé. Ajoutez vos produits et vos prix : vos offres seront proposées aux chantiers après vérification de votre entreprise."), "ok")
                    return redirect(url_for("supplier_catalog"))
                if role == "inspecteur":
                    flash(_("Compte créé. Après vérification de vos qualifications, ChantierVrai vous attribue des inspections dans votre zone et vous paie chaque visite."), "ok")
                return redirect(url_for("home"))
            except DB.integrity_errors():
                flash(_('Un compte existe déjà avec cet e-mail.'), "error")
    return render_template("register.html")


@app.route("/connexion", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if too_many_attempts(email):
            flash(_("Trop d'essais. Réessayez dans 15 minutes ou réinitialisez votre mot de passe."), "error")
            return render_template("login.html"), 429
        user = get_db().execute("SELECT * FROM users WHERE email = ? AND deleted = 0", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            if user["blocked"]:
                flash(_('Ce compte est suspendu. Contactez le support.'), "error")
                return render_template("login.html"), 403
            nxt = request.args.get("next", "")
            nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home")
            if user["totp_on"]:
                chosen = session.get("lang")
                session.clear()
                if chosen:
                    session["lang"] = chosen
                session["pending_2fa"] = user["id"]
                session["pending_next"] = nxt
                return redirect(url_for("login_code"))
            start_session(user)
            return redirect(nxt)
        record_failure(email)
        flash(_('E-mail ou mot de passe incorrect.'), "error")
    return render_template("login.html")


@app.route("/connexion/code", methods=["GET", "POST"])
def login_code():
    uid = session.get("pending_2fa")
    if not uid:
        return redirect(url_for("login"))
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if request.method == "POST":
        key = f"2fa:{uid}"
        if too_many_attempts(key):
            session.clear()
            flash(_("Trop d'essais. Reconnectez-vous dans 15 minutes."), "error")
            return redirect(url_for("login"))
        code = request.form.get("code", "")
        ok = SEC.totp_ok(user["totp_secret"], code)
        if not ok:
            codes = json.loads(user["backup_codes"] or "[]")
            h = SEC.hash_code(code)
            if h in codes:
                codes.remove(h)
                db.execute("UPDATE users SET backup_codes = ? WHERE id = ?", (json.dumps(codes), uid))
                db.commit()
                ok = True
                left = len(codes)
        if ok:
            nxt = session.get("pending_next") or url_for("home")
            start_session(user)
            if not SEC.totp_ok(user["totp_secret"], code):
                flash(_('Code de secours utilisé. Il vous en reste %(left)s.', left=left), "ok")
            return redirect(nxt)
        record_failure(key)
        flash(_('Code incorrect.'), "error")
    return render_template("login_code.html")


@app.route("/deconnexion", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def create_reset_link(db, user):
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), user["id"],
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
    db.commit()
    return url_for("reset_password", token=token)


@app.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        if not too_many_attempts("reset:" + email):
            record_failure("reset:" + email)        # limite les demandes repetees
            user = db.execute("SELECT * FROM users WHERE email = ? AND deleted = 0 AND blocked = 0",
                              (email,)).fetchone()
            if user:
                path = create_reset_link(db, user)
                for ch in ("email", "whatsapp", "sms"):
                    if ch == "email" or user[f"notify_{ch}"]:
                        db.execute("INSERT INTO notifications (user_id, channel, title, body, link, status, is_read, "
                                   "created_at) VALUES (?,?,?,?,?,?,1,?)",
                                   (user["id"], ch, "Réinitialisation du mot de passe",
                                    "Ce lien est valable 1 heure. Si vous n'avez rien demandé, ignorez ce message.",
                                    path, "en_attente", now_iso()))
                db.commit()
                ids = [r[0] for r in db.execute("SELECT id FROM notifications WHERE user_id = ? AND status = 'en_attente' "
                                                "AND title = 'Réinitialisation du mot de passe'", (user["id"],))]
                run_async(_send_pending, ids)
        flash(_("Si un compte existe avec cette adresse, un lien de réinitialisation vient d'être envoyé (e-mail, WhatsApp ou SMS). Il est valable 1 heure."), "ok")
        return redirect(url_for("login"))
    return render_template("forgot.html")


@app.route("/reinitialiser/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()
    row = db.execute("SELECT * FROM reset_tokens WHERE token_hash = ? AND used = 0",
                     (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        flash(_("Ce lien n'est plus valable. Refaites une demande."), "error")
        return redirect(url_for("forgot_password"))
    user = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if request.method == "POST":
        pw = request.form.get("password", "")
        problem = SEC.password_problem(pw, user["email"])
        if problem:
            flash(problem, "error")
        elif pw != request.form.get("password2"):
            flash(_('Les deux mots de passe sont différents.'), "error")
        else:
            db.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                       (generate_password_hash(pw), user["id"]))
            db.execute("UPDATE reset_tokens SET used = 1 WHERE user_id = ?", (user["id"],))
            db.execute("DELETE FROM login_attempts WHERE key = ?", ("e:" + user["email"],))
            db.commit()
            session.clear()
            flash(_('Mot de passe changé. Toutes les autres sessions sont déconnectées. Connectez-vous.'), "ok")
            return redirect(url_for("login"))
    return render_template("reset.html")


@app.route("/compte", methods=["GET", "POST"])
@login_required
def account():
    me = current_user()
    if request.method == "POST":
        f = request.form
        db = get_db()
        db.execute("UPDATE users SET name = ?, phone = ?, notify_whatsapp = ?, notify_sms = ?, notify_email = ?, "
                   "zone = ?, tarif = ?, bio = ? WHERE id = ?",
                   (f.get("name", me["name"]).strip() or me["name"], f.get("phone", "").strip(),
                    1 if f.get("notify_whatsapp") else 0, 1 if f.get("notify_sms") else 0,
                    1 if f.get("notify_email") else 0, f.get("zone", "").strip()[:80] or None,
                    to_int(f.get("tarif"), None), f.get("bio", "").strip()[:500] or None, me["id"]))
        db.execute("UPDATE users SET advanced = ? WHERE id = ?", (1 if f.get("advanced") else 0, me["id"]))
        if is_contractor(me):
            company = f.get("company", "").strip()[:150] or None
            want = 1 if f.get("verify_requested") else 0
            if want and not company:
                flash(_("Indiquez le nom de votre entreprise et son RCCM pour demander la vérification."), "error")
                want = 0
            db.execute("UPDATE users SET company = ?, verify_requested = ? WHERE id = ?", (company, want, me["id"]))
            if want and not me["verify_requested"] and not me["verified"]:
                notify(None, admins(db, "verify"), L("Entrepreneur à vérifier"),
                       L("%(n)s demande la vérification de son entreprise.", n=me["name"]), "/admin", db=db)
        db.commit()
        flash(_('Compte mis à jour.'), "ok")
        return redirect(url_for("account"))
    channels = {c: NOTIFY.configured(c) for c in ("whatsapp", "sms", "email")}
    return render_template("account.html", channels=channels)


@app.route("/compte/securite", methods=["GET", "POST"])
@login_required
def security():
    me = current_user()
    db = get_db()
    new_codes = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            pw = request.form.get("password", "")
            problem = SEC.password_problem(pw, me["email"])
            if not check_password_hash(me["password_hash"], request.form.get("current", "")):
                flash(_('Mot de passe actuel incorrect.'), "error")
            elif problem:
                flash(problem, "error")
            else:
                db.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                           (generate_password_hash(pw), me["id"]))
                db.commit()
                start_session(db.execute("SELECT * FROM users WHERE id = ?", (me["id"],)).fetchone())
                flash(_('Mot de passe changé. Vos autres appareils sont déconnectés.'), "ok")
        elif action == "totp_start":
            session["totp_setup"] = SEC.new_secret()
        elif action == "totp_confirm":
            secret = session.get("totp_setup")
            if secret and SEC.totp_ok(secret, request.form.get("code")):
                new_codes = SEC.backup_codes()
                db.execute("UPDATE users SET totp_secret = ?, totp_on = 1, backup_codes = ? WHERE id = ?",
                           (secret, json.dumps([SEC.hash_code(c) for c in new_codes]), me["id"]))
                db.commit()
                session.pop("totp_setup", None)
                flash(_('Double authentification activée.'), "ok")
            else:
                flash(_("Code incorrect. Vérifiez l'heure de votre téléphone et réessayez."), "error")
        elif action == "totp_off":
            if check_password_hash(me["password_hash"], request.form.get("current", "")):
                db.execute("UPDATE users SET totp_on = 0, totp_secret = NULL, backup_codes = NULL WHERE id = ?",
                           (me["id"],))
                db.commit()
                flash(_('Double authentification désactivée.'), "ok")
            else:
                flash(_('Mot de passe incorrect.'), "error")
        elif action == "logout_all":
            db.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (me["id"],))
            db.commit()
            start_session(db.execute("SELECT * FROM users WHERE id = ?", (me["id"],)).fetchone())
            flash(_('Tous vos autres appareils sont déconnectés.'), "ok")
        if new_codes is None:
            return redirect(url_for("security"))
        g.pop("user", None)
    me = current_user()
    setup = session.get("totp_setup")
    return render_template("security.html", setup=setup, setup_group=SEC.group(setup) if setup else None,
                           uri=SEC.otpauth_uri(setup, me["email"]) if setup else None, new_codes=new_codes)


@app.route("/compte/export")
@login_required
def export_data():
    me = current_user()
    db = get_db()
    rows = lambda q, *a: [dict(r) for r in db.execute(q, a)]
    user = {k: me[k] for k in me.keys() if k not in ("password_hash", "totp_secret", "backup_codes")}
    data = {
        "export_du": now_iso(), "compte": user,
        "chantiers": rows("SELECT * FROM projects WHERE owner_id = ? OR chef_id = ? OR id IN "
                          "(SELECT project_id FROM project_members WHERE user_id = ?)", me["id"], me["id"], me["id"]),
        "preuves_envoyees": rows("SELECT id, project_id, step_id, note, created_at, photo_lat, photo_lng, device_lat, "
                                 "device_lng, distance, ok, reasons, kind FROM proofs WHERE user_id = ?", me["id"]),
        "notifications": rows("SELECT channel, title, body, status, created_at FROM notifications WHERE user_id = ?",
                              me["id"]),
        "factures_envoyees": rows("SELECT id, project_id, supplier, number, inv_date, total, created_at FROM invoices "
                                  "WHERE user_id = ?", me["id"]),
        "inspections": rows("SELECT * FROM inspections WHERE inspector_id = ? OR requested_by = ?", me["id"], me["id"]),
    }
    resp = Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")
    resp.headers["Content-Disposition"] = "attachment; filename=mes-donnees-chantiervrai.json"
    return resp


def account_deletion_blocker(db, me):
    """Raison qui empêche de supprimer le compte (argent au séquestre, litige en cours), ou None."""
    for p in db.execute("SELECT * FROM projects WHERE owner_id = ?", (me["id"],)).fetchall():
        esc = escrow(p["id"], db)
        if esc["balance"] > 0 or esc["pending_out"] > 0:
            return _("Le séquestre du chantier « %(name)s » contient encore de l'argent. Faites-le rembourser par le support avant de supprimer votre compte.", name=p['name'])
    if db.execute("SELECT 1 FROM disputes d JOIN projects p ON p.id = d.project_id WHERE d.status IN ('ouvert', 'en_appel') AND "
                  "(p.owner_id = ? OR p.chef_id = ?)", (me["id"], me["id"])).fetchone():
        return _("Un litige est en cours sur l'un de vos chantiers : il doit être résolu avant la suppression.")
    return None


def anonymize_account(db, me):
    """Suppression du compte : données personnelles effacées, sessions et jetons des applications coupés.
    L'historique des chantiers des autres utilisateurs reste cohérent (« Compte supprimé »)."""
    db.execute("UPDATE users SET name = 'Compte supprimé', email = ?, phone = NULL, password_hash = ?, "
               "totp_secret = NULL, totp_on = 0, backup_codes = NULL, zone = NULL, bio = NULL, deleted = 1, "
               "session_version = session_version + 1 WHERE id = ?",
               (f"supprime-{me['id']}-{secrets.token_hex(4)}@chantiervrai.invalid", secrets.token_hex(32), me["id"]))
    db.execute("DELETE FROM project_members WHERE user_id = ?", (me["id"],))
    db.execute("UPDATE api_tokens SET revoked = 1 WHERE user_id = ?", (me["id"],))
    db.execute("DELETE FROM devices WHERE user_id = ?", (me["id"],))
    db.commit()


@app.route("/compte/supprimer", methods=["POST"])
@login_required
def delete_account():
    me = current_user()
    db = get_db()
    if not check_password_hash(me["password_hash"], request.form.get("current", "")):
        flash(_('Mot de passe incorrect.'), "error")
        return redirect(url_for("security"))
    reason = account_deletion_blocker(db, me)
    if reason:
        flash(reason, "error")
        return redirect(url_for("security"))
    anonymize_account(db, me)
    session.clear()
    flash(_('Votre compte a été supprimé et vos données personnelles effacées.'), "ok")
    return redirect(url_for("login"))


@app.route("/fournisseur/conditions", methods=["GET", "POST"])
def supplier_terms():
    """Conditions fournisseur : commission ChantierVrai, facturation mensuelle, impayes. Acceptees a l'inscription."""
    me = current_user()
    if request.method == "POST":
        if not me or me["role"] != "fournisseur" or not request.form.get("accept"):
            abort(403)
        db = get_db()
        db.execute("UPDATE users SET supplier_terms_at = ? WHERE id = ?", (now_iso(), me["id"]))
        db.commit()
        flash(_("Conditions acceptées : votre catalogue peut être proposé aux chantiers."), "ok")
        return redirect(url_for("home"))
    return render_template("supplier_terms.html", rate=commission_pct(), company=env("COMPANY_NAME", "[Nom de la société]"))


@app.route("/cgu")
def terms():
    return render_template("legal_terms_en.html" if g.lang == "en" else "legal_terms.html", company=env("COMPANY_NAME", "[Nom de la société]"),
                           contact=env("CONTACT_EMAIL", "[e-mail de contact]"))


@app.route("/confidentialite")
def privacy():
    return render_template("legal_privacy_en.html" if g.lang == "en" else "legal_privacy.html", company=env("COMPANY_NAME", "[Nom de la société]"),
                           contact=env("CONTACT_EMAIL", "[e-mail de contact]"))


@app.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    me = current_user()
    db = get_db()
    if request.method == "POST":
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (me["id"],))
        db.commit()
        return redirect(url_for("notifications"))
    rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100",
                      (me["id"],)).fetchall()
    return render_template("notifications.html", rows=rows)


# --------------------------------------------------------------------------
# Chantiers
# --------------------------------------------------------------------------
def user_projects(user, db=None):
    db = db or get_db()
    if user["role"] == "proprio":
        return db.execute("SELECT * FROM projects WHERE owner_id = ? OR id IN (SELECT project_id FROM project_members "
                          "WHERE user_id = ? AND role IN ('coproprio', 'finance')) ORDER BY id DESC", (user["id"], user["id"])).fetchall()
    if user["role"] == "chef":
        return db.execute("SELECT * FROM projects WHERE chef_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
    if user["role"] == "fournisseur":
        return []
    if user["role"] == "pro":
        return db.execute("SELECT * FROM projects WHERE id IN (SELECT project_id FROM project_members WHERE user_id = ?) "
                          "ORDER BY id DESC", (user["id"],)).fetchall()
    return db.execute("SELECT * FROM projects WHERE id IN (SELECT project_id FROM inspections WHERE inspector_id = ? "
                      "AND status IN ('acceptee','realisee')) OR id IN (SELECT project_id FROM project_members WHERE "
                      "user_id = ? AND role = 'controleur') ORDER BY id DESC", (user["id"], user["id"])).fetchall()


@app.route("/produit")
def product():
    """Page de presentation du produit (visiteurs)."""
    return render_template("product.html", contact=env("CONTACT_EMAIL"), store_android=env("ANDROID_STORE_URL"),
                           store_ios=env("IOS_STORE_URL"))


@app.route("/")
def home():
    user = current_user()
    if not user:
        return product()
    db = get_db()
    cards, trusts = [], {}
    for p in user_projects(user):
        s = project_stats(p["id"])
        pred = project_prediction(p, s)
        cards.append((p, s, pred))
        if user["role"] == "proprio":
            trusts[p["id"]] = project_trust(p, s, pred, db)
    inspections = []
    if user["role"] == "inspecteur":
        inspections = db.execute(
            "SELECT i.*, p.name AS project_name, p.address, st.name AS step_name, u.name AS owner_name, u.phone AS owner_phone "
            "FROM inspections i JOIN projects p ON p.id = i.project_id LEFT JOIN steps st ON st.id = i.step_id "
            "JOIN users u ON u.id = i.requested_by WHERE i.inspector_id = ? ORDER BY i.id DESC", (user["id"],)).fetchall()
    covers = {}
    if cards:
        ids = [c[0]["id"] for c in cards]
        marks = ",".join("?" * len(ids))
        for r in db.execute(f"SELECT project_id, MAX(id) AS pid FROM proofs WHERE ok = 1 AND project_id IN ({marks}) "
                            "AND (kind IS NULL OR kind != 'video' OR thumb IS NOT NULL) GROUP BY project_id", ids):
            covers[r["project_id"]] = r["pid"]
        for r in db.execute(f"SELECT project_id, MAX(created_at) AS at FROM proofs WHERE ok = 1 AND project_id IN ({marks}) "
                            "GROUP BY project_id", ids):
            covers[f"at{r['project_id']}"] = r["at"]
    activity = db.execute("SELECT title, body, link, project_id, created_at, is_read FROM notifications WHERE user_id = ? "
                          "AND channel = 'app' ORDER BY id DESC LIMIT 4", (user["id"],)).fetchall()
    portfolio = None
    if user["role"] == "proprio" and cards:
        portfolio = {
            "n": len(cards), "total": sum(s["total"] for _p, s, _r in cards),
            "paid": sum(s["paid"] for _p, s, _r in cards),
            "late": sum(1 for _p, _s, r in cards if r and r["delay"] > 7 and not r["done"]),
            "to_validate": sum(s["to_validate"] for _p, s, _r in cards),
        }
    orders = []
    if user["role"] == "fournisseur":
        orders = project_orders(db, supplier_id=user["id"])
    if portfolio:
        scores = [t["score"] for t in trusts.values() if t["score"] is not None]
        portfolio["trust"] = round(sum(scores) / len(scores)) if scores else None
        portfolio["low_trust"] = sum(1 for x in scores if x < 60)
    controlled, pending_checks = [], {}
    if user["role"] == "inspecteur":
        controlled = [r[0] for r in db.execute("SELECT project_id FROM project_members WHERE user_id = ? AND role = 'controleur'",
                                               (user["id"],))]
        for r in db.execute("SELECT c.project_id, COUNT(*) AS n FROM step_checks c JOIN steps st ON st.id = c.step_id "
                            "WHERE c.status = 'a_faire' AND c.required = 1 AND st.status IN ('en_cours', 'declare') "
                            "GROUP BY c.project_id"):
            pending_checks[r["project_id"]] = r["n"]
    return render_template("home.html", cards=cards, inspections=inspections, portfolio=portfolio, orders=orders,
                           trusts=trusts, controlled=controlled, pending_checks=pending_checks, covers=covers, activity=activity,
                           onboarding=onboarding(db, user, [c[0] for c in cards]))


def whatsapp_invite(p):
    """Lien WhatsApp pret a envoyer au chef de chantier, avec le code d'invitation."""
    from urllib.parse import quote
    text = _("Bonjour, je suis le chantier « %(name)s » avec ChantierVrai. Installez l'application, créez un compte « Chef de chantier » "
             "et entrez le code %(code)s pour le rejoindre : %(url)s", name=p["name"], code=p["invite_code"],
             url=public_url("/") or request.host_url)
    return "https://wa.me/?text=" + quote(text)


def onboarding(db, user, projects):
    """Liste « Bien demarrer » : chaque point se coche tout seul quand c'est fait."""
    if not user or user["onboarding_hidden"] or user["role"] not in ("proprio", "chef"):
        return None
    if user["role"] == "proprio" and projects and not any(p["owner_id"] == user["id"] for p in projects):
        return None                      # co-proprietaire ou responsable financier : ce n'est pas son chantier a lancer
    pids = [p["id"] for p in projects] or [0]
    marks = ",".join("?" * len(pids))
    items = []
    if user["role"] == "proprio":
        first = projects[0] if projects else None
        no_chef = next((p for p in projects if not p["chef_id"]), None)
        items.append((_("Créer votre premier chantier"), bool(projects),
                      _("Nom, position du terrain, budget : 3 minutes."), url_for("new_project"), None))
        items.append((_("Inviter votre chef de chantier"), bool(projects) and not no_chef,
                      _("Envoyez-lui le code %(code)s par WhatsApp : il installe l'application et rejoint le chantier.",
                        code=no_chef["invite_code"]) if no_chef else _("Il envoie ensuite ses photos depuis le terrain."),
                      whatsapp_invite(no_chef) if no_chef else (url_for("project", project_id=first["id"]) if first else None),
                      _("Envoyer par WhatsApp") if no_chef else None))
        items.append((_("Ajouter votre téléphone pour les alertes"), bool(user["phone"]),
                      _("Étape à valider, photo refusée, paiement : vous êtes prévenu sur WhatsApp."), url_for("account"), None))
        items.append((_("Recevoir une première photo vérifiée"),
                      bool(db.execute(f"SELECT 1 FROM proofs WHERE ok = 1 AND project_id IN ({marks})", pids).fetchone()),
                      _("Chaque photo est contrôlée : position GPS, date, prise avec l'application."),
                      url_for("project", project_id=first["id"], onglet="preuves") if first else None, None))
        items.append((_("Valider une première étape et la payer"),
                      bool(db.execute(f"SELECT 1 FROM steps WHERE status IN ('versement', 'paye') AND project_id IN ({marks})",
                                      pids).fetchone()),
                      _("Vous vérifiez les preuves, vous validez, puis vous payez avec le bon à payer."),
                      url_for("project", project_id=first["id"], onglet="etapes") if first else None, None))
        if billing_enforced():
            v = sub_view(db, user)
            items.append((_("Choisir votre offre"), v["status"] in ("actif", "impaye"),
                          _("L'essai gratuit dure 30 jours ; vos chantiers restent accessibles ensuite."),
                          url_for("subscription"), None))
    else:
        items.append((_("Rejoindre le chantier avec le code du propriétaire"), bool(projects),
                      _("Le code est dans le message du propriétaire."), None, None))
        items.append((_("Renseigner votre numéro Mobile Money"), bool(user["phone"]),
                      _("Il figure sur les bons à payer : le propriétaire vous paie au bon numéro."), url_for("account"), None))
        items.append((_("Installer l'application sur votre téléphone"),
                      bool(db.execute("SELECT 1 FROM devices WHERE user_id = ?", (user["id"],)).fetchone()),
                      _("Les photos prises avec l'application sont acceptées même sans réseau."), None, None))
        items.append((_("Envoyer une première photo"),
                      bool(db.execute("SELECT 1 FROM proofs WHERE user_id = ?", (user["id"],)).fetchone()),
                      _("Sur le terrain, à moins de 100 m du chantier."),
                      url_for("project", project_id=projects[0]["id"]) if projects else None, None))
    done = sum(1 for it in items if it[1])
    if done == len(items):
        return None
    return {"items": items, "done": done, "total": len(items)}


@app.route("/bien-demarrer/masquer", methods=["POST"])
@login_required
def hide_onboarding():
    db = get_db()
    db.execute("UPDATE users SET onboarding_hidden = 1 WHERE id = ?", (current_user()["id"],))
    db.commit()
    return redirect(url_for("home"))


def project_orders(db, project_id=None, supplier_id=None):
    where, args = ("o.project_id = ?", (project_id,)) if project_id else ("o.supplier_id = ?", (supplier_id,))
    return db.execute("SELECT o.*, p.name AS project_name, p.address, u.name AS supplier_name, st.name AS step_name "
                      "FROM orders o JOIN projects p ON p.id = o.project_id JOIN users u ON u.id = o.supplier_id "
                      "JOIN steps st ON st.id = o.step_id WHERE " + where + " ORDER BY o.id DESC", args).fetchall()


@app.route("/chantiers/nouveau", methods=["GET", "POST"])
@role_required("proprio")
def new_project():
    user = current_user()
    if billing_enforced():
        v = sub_view(get_db(), user)
        if not v["can_create"]:
            flash(_("Votre essai est terminé ou votre abonnement est suspendu : choisissez une offre pour créer un chantier.")
                  if v["blocked"] else _("Votre offre permet %(n)s chantier(s) en cours. Passez à l'offre supérieure pour en ajouter.",
                                         n=v["limit"]), "error")
            return redirect(url_for("subscription"))
    if request.method == "POST":
        f = request.form
        lat, lng = to_float(f.get("lat")), to_float(f.get("lng"))
        steps = []
        for i in range(12):
            n = f.get(f"step_name_{i}", "").strip()
            if n:
                steps.append((n, to_int(f.get(f"step_amount_{i}")), to_int(f.get(f"step_days_{i}"), None)))
        start = f.get("start_date", "").strip() or date.today().isoformat()
        try:
            date.fromisoformat(start)
        except ValueError:
            start = date.today().isoformat()
        if not f.get("name", "").strip() or lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            flash(_('Indiquez le nom du chantier et des coordonnées GPS valides.'), "error")
        elif not steps:
            flash(_('Ajoutez au moins une étape.'), "error")
        else:
            pid = create_project(get_db(), user["id"], f["name"].strip(), f.get("address", "").strip(), lat, lng,
                                 int(to_float(f.get("radius")) or 100), steps, start,
                                 kind="public" if f.get("kind") == "public" else "prive",
                                 pay_mode=allowed_pay_mode(f.get("pay_mode"), fallback="manuel"),
                                 description=f.get("description", "").strip()[:2000],
                                 require_app_capture=1 if f.get("require_app_capture") else 0)
            get_db().execute("UPDATE projects SET auto_validate = ?, require_inspection = ? WHERE id = ?",
                             (1 if f.get("auto_validate") and auto_validate_on() else 0,
                              1 if f.get("require_inspection") else 0, pid))
            if f.get("auto_validate") and auto_validate_on():
                log(pid, L("Validation automatique acceptée par le propriétaire : étape validée après %(n)s jours sans réponse",
                           n=auto_validate_days()), get_db(), user["id"])
            get_db().commit()
            flash(_("Chantier créé. Donnez le code d'invitation à votre chef de chantier."), "ok")
            return redirect(url_for("project", project_id=pid))
    sub = get_sub(get_db(), user)
    return render_template("new_project.html", default_steps=DEFAULT_STEPS, public_steps=PUBLIC_STEPS,
                           default_total=sum(a for _n, a, _d in DEFAULT_STEPS),
                           default_inspection=bool(sub and sub["plan"] == "entreprise"), insp_price=inspection_prices()[0],
                           today=date.today().isoformat())


def site_distance(p, lat, lng):
    """(distance en m, limite en m, controle par la parcelle ?). La parcelle dessinee remplace le cercle."""
    pts = GEO.parse(p["parcel"]) if p["parcel"] else None
    if pts:
        return round(GEO.distance_m(pts, lat, lng)), PARCEL_TOLERANCE, True
    return round(haversine(lat, lng, p["lat"], p["lng"])), p["radius"], False


def create_project(db, owner_id, name, address, lat, lng, radius, steps, start, kind="prive", pay_mode="manuel",
                   description="", market=None, require_app_capture=0):
    market = market or {}
    cur = db.execute(
        "INSERT INTO projects (owner_id, name, address, lat, lng, radius, invite_code, created_at, kind, pay_mode, "
        "start_date, description, marche_ref, ao_ref, autorite, attributaire, montant_marche, sigomap_url, is_public, "
        "require_app_capture) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id, name, address, lat, lng, max(radius, 20), secrets.token_hex(3).upper(), now_iso(), kind, pay_mode,
         start, description, market.get("marche_ref"), market.get("ao_ref"), market.get("autorite"),
         market.get("attributaire"), market.get("montant_marche"), market.get("sigomap_url"),
         1 if market.get("is_public") else 0, require_app_capture))
    pid = cur.lastrowid
    for pos, (n, amount, days) in enumerate(steps):
        db.execute("INSERT INTO steps (project_id, position, name, amount, status, planned_days, started_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (pid, pos, n, amount, "en_cours" if pos == 0 else "attente", days, now_iso() if pos == 0 else None))
    log(pid, L('Chantier créé'), db, owner_id)
    return pid


@app.route("/rejoindre", methods=["POST"])
@role_required("chef")
def join_project():
    user = current_user()
    code = request.form.get("code", "").strip().upper()
    db = get_db()
    p = db.execute("SELECT * FROM projects WHERE invite_code = ?", (code,)).fetchone()
    if p is None:
        flash(_("Code d'invitation inconnu."), "error")
    elif p["chef_id"] and p["chef_id"] != user["id"]:
        flash(_('Ce chantier a déjà un chef de chantier.'), "error")
    else:
        db.execute("UPDATE projects SET chef_id = ? WHERE id = ?", (user["id"], p["id"]))
        log(p["id"], L('%(name)s a rejoint le chantier comme chef de chantier', name=user['name']))
        notify(p["id"], owners_of(p), L('Chef de chantier connecté'),
               L('%(name)s a rejoint « %(name2)s ».', name=user['name'], name2=p['name']), url_for("project", project_id=p["id"]))
        db.commit()
        flash(_('Vous avez rejoint le chantier.'), "ok")
        return redirect(url_for("project", project_id=p["id"]))
    return redirect(url_for("home"))


def new_capture_token(db, project_id):
    tok = secrets.token_urlsafe(18)
    db.execute("INSERT INTO capture_tokens (token, user_id, project_id, issued_at) VALUES (?,?,?,?)",
               (tok, current_user()["id"], project_id, now_iso()))
    db.execute("DELETE FROM capture_tokens WHERE issued_at < ?",
               ((datetime.now(timezone.utc) - timedelta(hours=OFFLINE_HOURS * 2)).isoformat(),))
    db.commit()
    return tok


def proofs_of(project_id, db=None):
    return (db or get_db()).execute(
        "SELECT proofs.*, steps.name AS step_name, users.name AS author FROM proofs "
        "JOIN steps ON steps.id = proofs.step_id JOIN users ON users.id = proofs.user_id "
        "WHERE proofs.project_id = ? ORDER BY proofs.id DESC", (project_id,)).fetchall()


def show_advanced(db, user, project_id):
    """Fonctions avancees (maquette, capteurs, 360°, zones, quantites) : sur demande, pour les pros,
    ou quand le chantier s'en sert deja."""
    if user["advanced"] or user["role"] in ("pro", "inspecteur"):
        return True
    return any(db.execute(f"SELECT 1 FROM {t} WHERE project_id = ? LIMIT 1", (project_id,)).fetchone()
               for t in ("zones", "pano_visits", "work_items", "sensors", "bim_models"))


@app.route("/chantiers/<int:project_id>")
@login_required
def project(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant"))
    role = g.project_role
    db = get_db()
    g.advanced = show_advanced(db, current_user(), project_id)
    tab = request.args.get("onglet", "accueil")
    if role == "owner":
        maybe_weekly_report(p)
    stats = project_stats(project_id)
    proofs = proofs_of(project_id)
    ok_by_step = {}
    for pr in proofs:
        if pr["ok"]:
            ok_by_step[pr["step_id"]] = ok_by_step.get(pr["step_id"], 0) + 1
    people = {r["id"]: r for r in db.execute(
        "SELECT id, name, phone, email FROM users WHERE id IN (?, ?)", (p["owner_id"], p["chef_id"] or 0))}
    ctx = dict(p=p, s=stats, proofs=proofs, ok_by_step=ok_by_step, people=people, tab=tab,
               pred=project_prediction(p, stats), schedule=PRED.step_schedule(p, stats["steps"]))
    seed_checks(db, project_id)
    ctx["zones"] = project_zones(db, project_id)
    ctx["checks_by_step"] = {}
    for c in db.execute("SELECT step_id, status, required FROM step_checks WHERE project_id = ?", (project_id,)):
        cs = ctx["checks_by_step"].setdefault(c["step_id"], {"ok": 0, "total": 0, "missing": 0})
        cs["total"] += 1
        cs["ok"] += c["status"] == "conforme"
        cs["missing"] += bool(c["required"] and c["status"] != "conforme")
    inspections = db.execute(
        "SELECT i.*, u.name AS inspector_name, u.phone AS inspector_phone, st.name AS step_name FROM inspections i "
        "JOIN users u ON u.id = i.inspector_id LEFT JOIN steps st ON st.id = i.step_id "
        "WHERE i.project_id = ? ORDER BY i.id DESC", (project_id,)).fetchall()
    ctx["inspections"] = inspections
    ctx["qual_by_step"] = quality_by_step(db, project_id)
    ctx["cover"] = db.execute("SELECT id, created_at FROM proofs WHERE project_id = ? AND ok = 1 AND "
                              "(kind IS NULL OR kind != 'video' OR thumb IS NOT NULL) ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
    ctx["land_level"] = land_risk(db, p) if role == "owner" else None
    ctx["land_label"] = LAND.label(LAND.RISK[ctx["land_level"]], g.lang) if ctx["land_level"] is not None else None
    ctx["notes_recent"] = db.execute("SELECT * FROM site_notes WHERE project_id = ? ORDER BY id DESC LIMIT 3", (project_id,)).fetchall()
    ctx["notes_unread"] = db.execute("SELECT COUNT(*) FROM site_notes WHERE project_id = ? AND read_at IS NULL", (project_id,)).fetchone()[0]
    ctx["qual_open"] = [dict(r, name=QUAL._p(QUAL.BY_SLUG[r["ouvrage"]]["name"], g.lang)) for r in db.execute(
        "SELECT id, ouvrage, label, status, score FROM quality_reviews WHERE project_id = ? AND status NOT IN ('clos') "
        "AND NOT EXISTS (SELECT 1 FROM quality_reviews n WHERE n.previous_id = quality_reviews.id) ORDER BY id DESC LIMIT 6",
        (project_id,))]
    if role in ("chef", "inspecteur"):
        ctx["capture_token"] = new_capture_token(db, p["id"])
    if role == "intervenant":
        ctx["documents"] = db.execute("SELECT * FROM documents WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
        ctx["activity"] = db.execute("SELECT a.*, u.name AS author FROM activity a LEFT JOIN users u ON u.id = a.user_id "
                                     "WHERE a.project_id = ? ORDER BY a.id DESC LIMIT 25", (project_id,)).fetchall()
        ctx["trust"] = project_trust(p, stats, ctx["pred"], db)
        ctx["member_role"] = g.get("member_role")
        ctx["rights"] = MEMBER_RIGHTS.get(g.get("member_role"), set())
        return render_template("project_member.html", **ctx)
    if role == "inspecteur":
        mine = [i for i in inspections if i["inspector_id"] == current_user()["id"]]
        resp = app.make_response(render_template("project_inspector.html", mine=mine, **ctx))
        resp.headers["X-CV-Offline"] = "1"
        return resp
    ctx["disputes"] = db.execute("SELECT * FROM disputes WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    if role == "chef":
        ctx["wa_number"], ctx["wa_link"] = (WA.display_number(), WA.wa_link()) if WA.configured() else (None, None)
        ctx["pending_pay"] = db.execute("SELECT id FROM payment_records WHERE project_id = ? AND payee_id = ? AND status = 'declare'",
                                        (project_id, current_user()["id"])).fetchall()
        if tab == "factures":
            ctx.update(invoice_context(project_id))
            ctx["orders"] = project_orders(db, project_id)
            ctx["ORDER_STATUS"] = {k: _(v) for k, v in ORDER_STATUS.items()}
        resp = app.make_response(render_template("project_chef.html", **ctx))
        if tab == "accueil":
            resp.headers["X-CV-Offline"] = "1"      # page gardee par l'application pour le mode hors ligne
        return resp

    ctx["activity"] = db.execute(
        "SELECT activity.*, users.name AS author FROM activity LEFT JOIN users ON users.id = activity.user_id "
        "WHERE project_id = ? ORDER BY activity.id DESC LIMIT 15", (project_id,)).fetchall()
    ctx["alerts"] = project_alerts(p, stats, ctx["pred"])
    if tab == "accueil":
        ctx["trust"] = project_trust(p, stats, ctx["pred"], db)
        if p["chef_id"]:
            ctx["chef_user"] = db.execute("SELECT * FROM users WHERE id = ?", (p["chef_id"],)).fetchone()
            ctx["my_review"] = db.execute("SELECT * FROM contractor_reviews WHERE project_id = ? AND author_id = ?",
                                          (project_id, current_user()["id"])).fetchone()
            ctx["can_review"] = bool(db.execute("SELECT 1 FROM steps WHERE project_id = ? AND status IN ('paye', 'versement')",
                                                (project_id,)).fetchone())
    ctx["finance"] = finance_members(db, p)
    ctx["last_report"] = db.execute("SELECT * FROM reports WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                                    (project_id,)).fetchone()
    if tab == "etapes":
        ctx["transactions"] = db.execute("SELECT * FROM transactions WHERE project_id = ? ORDER BY id DESC",
                                         (project_id,)).fetchall()
        ctx["provider"] = PAY.get_provider()
        ctx["pv_by_step"] = {r["step_id"]: r["id"] for r in db.execute(
            "SELECT id, step_id FROM documents WHERE project_id = ? AND category = 'PV' ORDER BY id", (project_id,))}
        ctx["insp_by_step"] = {}
        for i in inspections:
            if i["status"] == "realisee" and i["step_id"] not in ctx["insp_by_step"]:
                ctx["insp_by_step"][i["step_id"]] = i
    if tab == "vues":
        ctx.update(views_context(p))
        ctx["imagery_orders"] = db.execute("SELECT * FROM imagery_orders WHERE project_id = ? ORDER BY id DESC",
                                           (project_id,)).fetchall()
    if tab == "dossier":
        ctx.update(invoice_context(project_id))
        ctx["orders"] = project_orders(db, project_id)
        ctx["ORDER_STATUS"] = {k: _(v) for k, v in ORDER_STATUS.items()}
        ctx["documents"] = db.execute("SELECT * FROM documents WHERE project_id = ? ORDER BY id DESC",
                                      (project_id,)).fetchall()
        ctx["insp_requests"] = db.execute("SELECT * FROM inspection_requests WHERE project_id = ? AND status IN "
                                          "('a_payer', 'a_attribuer') ORDER BY id", (project_id,)).fetchall()
        ctx["insp_price"] = inspection_prices(db)[0]
        ctx["inspectors"] = db.execute("SELECT * FROM users WHERE role = 'inspecteur' AND verified = 1 AND blocked = 0 "
                                       "AND deleted = 0 ORDER BY zone, name").fetchall()
        ctx["disputes"] = db.execute("SELECT * FROM disputes WHERE project_id = ? ORDER BY id DESC",
                                     (project_id,)).fetchall()
        ctx["signalements"] = db.execute("SELECT * FROM signalements WHERE project_id = ? ORDER BY id DESC",
                                         (project_id,)).fetchall()
        ctx["members"] = db.execute("SELECT u.id, u.name, u.email, m.role AS member_role FROM project_members m JOIN users u ON u.id = m.user_id "
                                    "WHERE m.project_id = ?", (project_id,)).fetchall()
        ctx["owner_user"] = db.execute("SELECT name FROM users WHERE id = ?", (p["owner_id"],)).fetchone()
    return render_template("project_owner.html", **ctx)


@app.route("/chantiers/<int:project_id>/planning", methods=["POST"])
@login_required
def update_planning(project_id):
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    start = request.form.get("start_date", "").strip()
    try:
        date.fromisoformat(start)
        db.execute("UPDATE projects SET start_date = ? WHERE id = ?", (start, project_id))
    except ValueError:
        flash(_('Date de début invalide.'), "error")
    for st in db.execute("SELECT id FROM steps WHERE project_id = ?", (project_id,)):
        v = request.form.get(f"days_{st['id']}")
        if v is not None:
            db.execute("UPDATE steps SET planned_days = ? WHERE id = ?", (to_int(v, None), st["id"]))
    log(p["id"], L('Planning mis à jour'))
    db.commit()
    flash(_('Planning enregistré. La prédiction des retards est mise à jour.'), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="etapes"))


LOCKED_STATUSES = ("declare", "versement", "paye")   # etapes dont le montant ne peut plus changer


@app.route("/chantiers/<int:project_id>/etapes/modifier", methods=["POST"])
@login_required
def edit_steps(project_id):
    """Renommer, changer le montant, ajouter, supprimer ou deplacer des etapes."""
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    f = request.form
    action = f.get("action", "save")
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    back = redirect(url_for("project", project_id=project_id, onglet="etapes", _anchor="modifier"))
    changes = []
    if action == "save":
        for st in steps:
            name = f.get(f"name_{st['id']}", st["name"]).strip()[:120] or st["name"]
            amount = to_int(f.get(f"amount_{st['id']}"), st["amount"])
            if st["status"] in LOCKED_STATUSES and amount != st["amount"]:
                flash(_('« %(name)s » est déjà déclarée ou payée : son montant ne peut plus changer.', name=st['name']), "error")
                amount = st["amount"]
            if name != st["name"] or amount != st["amount"]:
                db.execute("UPDATE steps SET name = ?, amount = ? WHERE id = ?", (name, amount, st["id"]))
                changes.append(_('« %(name)s » → « %(name2)s », %(amount)s FCFA', name=st['name'], name2=name, amount=format(amount, ',')).replace(",", " ")
                               if amount != st["amount"] else _('« %(name)s » renommée « %(name2)s »', name=st['name'], name2=name))
    elif action == "add":
        name = f.get("new_name", "").strip()[:120]
        if not name:
            flash(_('Donnez un nom à la nouvelle étape.'), "error")
            return back
        amount, days = to_int(f.get("new_amount")), to_int(f.get("new_days"), None)
        has_current = any(st["status"] in ("en_cours", "declare") for st in steps)
        status = "attente" if has_current or not steps else "en_cours"
        if not steps:
            status = "en_cours"
        db.execute("INSERT INTO steps (project_id, position, name, amount, status, planned_days, started_at) "
                   "VALUES (?,?,?,?,?,?,?)", (project_id, (steps[-1]["position"] + 1) if steps else 0, name, amount,
                                              status, days, now_iso() if status == "en_cours" else None))
        changes.append(_('étape ajoutée : « %(name)s », %(amount)s FCFA', name=name, amount=format(amount, ',')).replace(",", " "))
    elif action in ("delete", "up", "down"):
        sid = to_int(f.get("step_id"))
        st = next((x for x in steps if x["id"] == sid), None)
        if st is None:
            abort(404)
        if st["status"] != "attente":
            flash(_('Seules les étapes à venir peuvent être supprimées ou déplacées.'), "error")
            return back
        if action == "delete":
            if db.execute("SELECT 1 FROM proofs WHERE step_id = ? UNION SELECT 1 FROM invoices WHERE step_id = ? "
                          "UNION SELECT 1 FROM inspections WHERE step_id = ?", (sid, sid, sid)).fetchone():
                flash(_('Cette étape a déjà des preuves, factures ou inspections : renommez-la plutôt.'), "error")
                return back
            db.execute("DELETE FROM materials_plan WHERE step_id = ?", (sid,))
            db.execute("DELETE FROM steps WHERE id = ?", (sid,))
            changes.append(_('étape supprimée : « %(name)s »', name=st['name']))
        else:
            i = steps.index(st)
            j = i - 1 if action == "up" else i + 1
            if 0 <= j < len(steps) and steps[j]["status"] == "attente":
                other = steps[j]
                db.execute("UPDATE steps SET position = ? WHERE id = ?", (other["position"], st["id"]))
                db.execute("UPDATE steps SET position = ? WHERE id = ?", (st["position"], other["id"]))
                changes.append(_('« %(name)s » déplacée', name=st['name']))
            else:
                flash(_('Une étape à venir ne peut pas passer avant une étape commencée.'), "error")
                return back
    if changes:
        log(project_id, L('Étapes modifiées : ') + " ; ".join(changes))
        notify(project_id, [p["chef_id"]] + owners_of(p), L('Étapes du chantier modifiées'), " ; ".join(changes)[:500],
               url_for("project", project_id=project_id))
        db.commit()
        flash(_('Étapes mises à jour. Le chef de chantier est prévenu.'), "ok")
    return back


@app.route("/chantiers/<int:project_id>/reglages", methods=["POST"])
@login_required
def project_settings(project_id):
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    what = request.form.get("setting", "capture")
    on = 1 if request.form.get("on") or request.form.get("require_app_capture") else 0
    if what == "auto_validate":
        if current_user()["id"] != p["owner_id"]:
            abort(403)
        if on and not auto_validate_on(db):
            abort(400)
        if not on and db.execute("SELECT 1 FROM steps WHERE project_id = ? AND status = 'declare'", (project_id,)).fetchone():
            flash(_("Une étape attend votre réponse : validez-la ou refusez-la avant de retirer la validation automatique."), "error")
            return redirect(url_for("project", project_id=project_id, onglet="etapes"))
        db.execute("UPDATE projects SET auto_validate = ? WHERE id = ?", (on, project_id))
        log(project_id, L("Validation automatique acceptée par le propriétaire : étape validée après %(n)s jours sans réponse",
                          n=auto_validate_days(db)) if on else L("Validation automatique retirée par le propriétaire"))
        if p["chef_id"]:
            notify(project_id, [p["chef_id"]], L("Règle du chantier modifiée"),
                   L("Validation automatique après %(n)s jours sans réponse du propriétaire : activée.", n=auto_validate_days(db))
                   if on else L("Validation automatique après %(n)s jours sans réponse du propriétaire : désactivée.",
                                n=auto_validate_days(db)), url_for("project", project_id=project_id))
        tab = "etapes"
    elif what == "inspection":
        if p["kind"] == "public" and not on:
            flash(_("Sur un chantier public, l'inspection des étapes critiques reste obligatoire."), "error")
            return redirect(url_for("project", project_id=project_id, onglet="dossier", _anchor="inspections"))
        db.execute("UPDATE projects SET require_inspection = ? WHERE id = ?", (on, project_id))
        log(project_id, L("Inspection indépendante obligatoire sur les étapes critiques") if on
            else L("Inspection indépendante facultative sur les étapes critiques"))
        tab = "dossier"
    else:
        db.execute("UPDATE projects SET require_app_capture = ? WHERE id = ?", (on, project_id))
        log(project_id, L("Caméra de l'application ") + (L('exigée') if on else L('non exigée')) + L(' pour les photos'))
        tab = "preuves"
    db.commit()
    flash(_('Réglage enregistré.'), "ok")
    return redirect(url_for("project", project_id=project_id, onglet=tab))


@app.route("/preuves/<int:proof_id>/publier", methods=["POST"])
@login_required
def publish_proof(proof_id):
    db = get_db()
    pr = db.execute("SELECT * FROM proofs WHERE id = ?", (proof_id,)).fetchone()
    if pr is None:
        abort(404)
    p = load_project(pr["project_id"], roles=("owner",))
    back = redirect(url_for("project", project_id=p["id"], onglet="preuves", _anchor=f"preuve-{proof_id}"))
    if pr["is_published"]:
        db.execute("UPDATE proofs SET is_published = 0 WHERE id = ?", (proof_id,))
        db.commit()
        flash(_('Photo retirée du portail.'), "ok")
        return back
    if not pr["ok"] or p["kind"] != "public":
        flash(_("Seules les preuves vérifiées d'un chantier public peuvent être publiées."), "error")
        return back
    src = pr["thumb"] if pr["kind"] == "video" else pr["filename"]
    if not src:
        flash(_("Cette vidéo n'a pas d'image à publier."), "error")
        return back
    img, n, available = VISION.blur_faces(Image.open(os.path.join(UPLOAD_DIR, src)))
    name = save_image(img, UPLOAD_DIR, 1600, prefix="pub_")
    db.execute("UPDATE proofs SET is_published = 1, public_file = ? WHERE id = ?", (name, proof_id))
    db.commit()
    if not available:
        flash(_("Photo publiée. Attention : le floutage automatique des visages n'est pas installé sur ce serveur (opencv). Vérifiez qu'aucun visage n'est reconnaissable."), "error")
    else:
        flash(_('Photo publiée sur le portail') + (_(', %(n)s visage(s) flouté(s).', n=n) if n else _(', aucun visage détecté.')), "ok")
    return back


@app.route("/chantiers/<int:project_id>/membres", methods=["POST"])
@login_required
def manage_members(project_id):
    p = load_project(project_id, roles=("owner",))
    me = current_user()
    db = get_db()
    back = redirect(url_for("project", project_id=project_id, onglet="dossier", _anchor="membres"))
    if me["id"] != p["owner_id"]:
        flash(_('Seul le propriétaire principal gère les co-propriétaires.'), "error")
        return back
    if request.form.get("action") == "remove":
        uid = to_int(request.form.get("user_id"))
        db.execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, uid))
        log(project_id, L('Co-propriétaire retiré'))
        db.commit()
        return back
    email = request.form.get("email", "").strip().lower()
    mrole = request.form.get("role", "coproprio")
    if mrole not in MEMBER_ROLES:
        abort(400)
    u = db.execute("SELECT * FROM users WHERE email = ? AND deleted = 0", (email,)).fetchone()
    if mrole in ("controleur", "ingenieur"):
        ok_ctrl = u is not None and u["verified"] and (
            (mrole == "controleur" and (u["role"] == "inspecteur" or (u["role"] == "pro" and u["profession"] == "bureau_controle")))
            or (mrole == "ingenieur" and u["role"] == "pro" and u["profession"] in ("ingenieur", "bureau_controle")))
        if not ok_ctrl:
            flash(_("Aucun compte vérifié de ce métier avec cet e-mail. Le bureau de contrôle ou l'ingénieur crée un compte « Professionnel du BTP » (ou « Inspecteur indépendant ») et attend la vérification de ses qualifications."), "error")
            return back
    elif mrole in ("coproprio", "finance"):
        if u is None or u["role"] != "proprio":
            flash(_("Aucun compte « Propriétaire » avec cet e-mail. Demandez-lui d'en créer un, puis réessayez."), "error")
            return back
    elif u is None or u["role"] != "pro":
        flash(_("Aucun compte « Professionnel du BTP » avec cet e-mail. Demandez-lui d'en créer un, puis réessayez."), "error")
        return back
    if u["id"] in (p["owner_id"], p["chef_id"]):
        flash(_('Cette personne participe déjà au chantier.'), "error")
        return back
    db.execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, u["id"]))
    db.execute("INSERT INTO project_members (project_id, user_id, role, created_at) VALUES (?,?,?,?)",
               (project_id, u["id"], mrole, now_iso()))
    log(project_id, L('%(name)s ajouté : %(role)s', name=u['name'], role=L(MEMBER_ROLES[mrole])))
    notify(project_id, [u["id"]], L('Vous suivez un nouveau chantier'),
           L('%(name)s vous a ajouté au chantier « %(name2)s » : %(role)s.', name=me['name'], name2=p['name'],
             role=L(MEMBER_ROLES[mrole])), url_for("project", project_id=project_id))
    db.commit()
    flash(_('%(name)s est ajouté au chantier : %(role)s.', name=u['name'], role=_(MEMBER_ROLES[mrole])), "ok")
    return back


MEMBER_ROLES = {"coproprio": "co-propriétaire", "finance": "responsable financier",
                "controleur": "contrôleur habilité (bureau de contrôle)", "ingenieur": "ingénieur (valide les contrôles)",
                "architecte": "architecte", "conducteur": "conducteur de travaux", "entrepreneur": "entrepreneur",
                "comptable": "comptable"}
# role sur le chantier -> espace ouvert
MEMBER_ACCESS = {"coproprio": "owner", "finance": "owner", "controleur": "inspecteur", "ingenieur": "inspecteur",
                 "architecte": "intervenant", "conducteur": "intervenant", "entrepreneur": "intervenant",
                 "comptable": "intervenant"}
# ce que chaque intervenant peut faire en plus de suivre le chantier
MEMBER_RIGHTS = {"architecte": {"documents", "maquette"}, "conducteur": {"stock", "capteurs", "checks_request"},
                 "entrepreneur": {"decompte", "stock"}, "comptable": {"decompte", "finances", "export"},
                 "ingenieur": {"documents", "maquette", "capteurs"}, "controleur": {"capteurs"}}


def member_can(right):
    return right in MEMBER_RIGHTS.get(g.get("member_role"), set())


# --------------------------------------------------------------------------
# Preuves : photos et videos
# --------------------------------------------------------------------------
def process_proof(p, step, user, source="chef", inspection_id=None, order_id=None):
    """Controle et enregistre une preuve. Retourne (ok, raisons) ou (None, message d'erreur)."""
    file = request.files.get("photo") or request.files.get("video")
    if not file or not file.filename:
        return None, "Prenez une photo ou une vidéo."
    ext = ext_of(file.filename) or "jpg"
    is_video = ext in MEDIA.VIDEO_EXT or (file.mimetype or "").startswith("video/")
    if not is_video and ext not in IMG_EXT:
        return None, "Format non accepté."
    raw = file.read()
    sha = hashlib.sha256(raw).hexdigest()
    db = get_db()
    dev_lat, dev_lng = to_float(request.form.get("lat")), to_float(request.form.get("lng"))
    dev_acc = to_float(request.form.get("acc"))
    tz_offset = to_float(request.form.get("tz_offset"))          # minutes, comme getTimezoneOffset()
    client_last_modified = to_float(request.form.get("last_modified"))  # ms
    client_now = to_float(request.form.get("client_now"))               # ms
    now_utc = datetime.now(timezone.utc)
    reasons = []
    thumb = None
    duration = None
    img_for_features = None

    taken_naive = None
    if is_video:
        ext = ext if ext in MEDIA.VIDEO_EXT else "mp4"
        name = f"{secrets.token_hex(12)}.{ext}"
        path = os.path.join(UPLOAD_DIR, name)
        with open(path, "wb") as fh:
            fh.write(raw)
        info = MEDIA.probe(path)
        photo_lat, photo_lng = info.get("lat"), info.get("lng")
        taken_utc = info.get("created")
        duration = info.get("duration")
        if duration and duration > MEDIA.MAX_SECONDS:
            reasons.append(L('Vidéo trop longue (%(round)s s, maximum %(MAX_SECONDS)s s)', round=round(duration), MAX_SECONDS=MEDIA.MAX_SECONDS))
        tname = name.rsplit(".", 1)[0] + "_v.jpg"
        if MEDIA.thumbnail(path, os.path.join(UPLOAD_DIR, tname)):
            thumb = tname
            img_for_features = Image.open(os.path.join(UPLOAD_DIR, tname))
    else:
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            return None, "Ce fichier n'est pas une image lisible."
        photo_lat, photo_lng, taken_naive = read_exif(img)
        taken_utc = None
        if taken_naive is not None and tz_offset is not None:
            taken_utc = (taken_naive + timedelta(minutes=tz_offset)).replace(tzinfo=timezone.utc)
        name = save_image(img, UPLOAD_DIR)
        img_for_features = img

    # 1. Position : fichier en priorite, sinon telephone
    if photo_lat is not None:
        ref_lat, ref_lng = photo_lat, photo_lng
    elif dev_lat is not None:
        ref_lat, ref_lng = dev_lat, dev_lng
    else:
        ref_lat = ref_lng = None
        reasons.append(L('Aucune position GPS (ni dans le fichier, ni du téléphone)'))
    distance = None
    if ref_lat is not None:
        distance, limit, by_parcel = site_distance(p, ref_lat, ref_lng)
        if distance > limit:
            reasons.append(L('Prise à %(distance)s m de la parcelle (limite %(radius)s m)', distance=distance, radius=limit)
                           if by_parcel else
                           L('Prise à %(distance)s m du terrain (limite %(radius)s m)', distance=distance, radius=limit))
    if request.form.get("mocked") == "1":
        reasons.append(L("Position GPS simulée par une application (faux GPS)"))
    if photo_lat is not None and dev_lat is not None:
        gap = haversine(photo_lat, photo_lng, dev_lat, dev_lng)
        if gap > COHERENCE_METERS:
            reasons.append(L('Position du fichier et du téléphone incohérentes (%(round)s m)', round=round(gap)))

    # 2. Fraicheur
    capture = request.form.get("capture") if not is_video else "video"
    delayed = None
    if capture in ("app", "native"):
        # Photo prise avec la camera integree : pas de galerie possible. Le jeton prouve que la
        # photo est posterieure a l'ouverture de la page ; le decalage d'horloge du telephone est corrige.
        tok = db.execute("SELECT * FROM capture_tokens WHERE token = ? AND user_id = ? AND project_id = ?",
                         (request.form.get("capture_token", ""), user["id"], p["id"])).fetchone()
        captured_at = to_float(request.form.get("captured_at"))
        offline = request.form.get("offline") == "1"
        if taken_naive is not None and capture == "app":
            reasons.append(L("Fichier importé présenté comme une capture de l'application"))
        elif tok is None or not captured_at or not client_now:
            reasons.append(L('Jeton de capture invalide : rechargez la page'))
        else:
            offset_ms = now_utc.timestamp() * 1000 - client_now
            captured = datetime.fromtimestamp((captured_at + offset_ms) / 1000, timezone.utc)
            issued = datetime.fromisoformat(tok["issued_at"])
            age = (now_utc - captured).total_seconds()
            taken_utc = taken_utc or captured
            if captured < issued - timedelta(minutes=2):
                reasons.append(L("Photo antérieure à l'ouverture de l'application"))
            elif offline and age <= OFFLINE_HOURS * 3600:
                if age > FRESH_MINUTES * 60:
                    delayed = round(age / 60)
            elif age > FRESH_MINUTES * 60:
                reasons.append(L('Prise de vue ancienne (date trop éloignée)'))
            db.execute("UPDATE capture_tokens SET uses = uses + 1 WHERE token = ?", (tok["token"],))
    att_status = None
    if capture == "native":
        att_status = check_attestation(request.form.get("attestation"), request.form.get("attestation_nonce"),
                                       request.form.get("platform"), user)
        if att_status == "refusee":
            reasons.append(L("Appareil ou application non reconnus (téléphone modifié ou application non officielle)"))
    if capture in ("app", "native"):
        pass
    elif capture == "whatsapp" and not is_video:
        # WhatsApp retire la date et la position du fichier : position partagee dans le fil, date de reception
        if p["require_app_capture"]:
            reasons.append(L("Ce chantier exige la caméra de l'application : photo reçue par WhatsApp refusée"))
        taken_utc = now_utc
    elif not is_video and ((p["require_app_capture"] and source == "chef") or source == "fournisseur"):
        reasons.append(L("Photo importée : ce chantier exige la caméra de l'application"))
    elif taken_utc is not None:
        if abs((now_utc - taken_utc).total_seconds()) > FRESH_MINUTES * 60:
            reasons.append(L('Prise de vue ancienne (date trop éloignée)'))
    elif client_last_modified and client_now:
        if client_now - client_last_modified > FRESH_MINUTES * 60 * 1000:
            reasons.append(L('Fichier ancien ou importé de la galerie'))
    else:
        reasons.append(L('Date de prise de vue inconnue'))

    # 3. Doublon exact, puis doublon visuel (photo d'ecran, recadrage)
    exact_dup = bool(db.execute("SELECT 1 FROM proofs WHERE sha256 = ?", (sha,)).fetchone())
    if exact_dup:
        reasons.append(L('Fichier déjà envoyé'))
    feat = sim_dist = sim_color = None
    sim_score = sim_ref = None
    suspect = 0
    if img_for_features is not None:
        feat = VISION.features(img_for_features)
        rows = db.execute("SELECT id, feat, created_at FROM proofs WHERE project_id = ? AND ok = 1 AND feat IS NOT NULL "
                          "ORDER BY id DESC LIMIT 200", (p["id"],)).fetchall()
        refs = [json.loads(r["feat"]) for r in rows]
        uniform = float(np.asarray(img_for_features.convert("L").resize((64, 64))).std()) < 6
        if refs:
            sim_dist, sim_color = VISION.compare(feat, refs)
            sim_score, i = VISION.nearest(feat, refs)
            near = rows[i]
            if not uniform and not exact_dup and sim_score is not None:
                if sim_score <= NEAR_DUP_REFUSE:
                    reasons.append(L("Image quasi identique à la preuve du %(d)s (photo d'écran ou recadrage ?)",
                                     d=format_d(near["created_at"])))
                elif sim_score <= NEAR_DUP_FLAG:
                    suspect, sim_ref = 1, near["id"]

    ok = 0 if reasons else 1
    cur = db.execute(
        "INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, note, created_at, photo_lat, photo_lng, "
        "photo_taken, device_lat, device_lng, device_acc, distance, ok, reasons, kind, source, thumb, duration, feat, "
        "sim_dist, sim_color, ai_status, inspection_id, capture, delayed_minutes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (p["id"], step["id"], user["id"], name, sha, request.form.get("note", "").strip()[:500], now_iso(),
         photo_lat, photo_lng, taken_utc.isoformat(timespec="seconds") if taken_utc else None,
         dev_lat, dev_lng, dev_acc, distance, ok, I18N.store_list(reasons), "video" if is_video else "photo", source,
         thumb, duration, json.dumps(feat) if feat else None, sim_dist, sim_color,
         "en_cours" if VISION.ai_enabled() and (thumb or not is_video) else "off", inspection_id,
         capture or "fichier", delayed))
    if att_status:
        db.execute("UPDATE proofs SET attestation = ? WHERE id = ?", (att_status, cur.lastrowid))
    if sim_score is not None:
        db.execute("UPDATE proofs SET sim_score = ?, sim_ref = ?, suspect = ? WHERE id = ?",
                   (round(sim_score, 3), sim_ref, suspect if ok else 0, cur.lastrowid))
    g.last_proof_suspect = bool(suspect and ok)
    if order_id:
        db.execute("UPDATE proofs SET order_id = ? WHERE id = ?", (order_id, cur.lastrowid))
    zid = to_int(request.form.get("zone_id"), None)
    if zid and db.execute("SELECT 1 FROM zones WHERE id = ? AND project_id = ?", (zid, p["id"])).fetchone():
        db.execute("UPDATE proofs SET zone_id = ? WHERE id = ?", (zid, cur.lastrowid))
    proof_id = cur.lastrowid
    g.last_proof_id = proof_id
    emit_event(db, p["id"], "preuve.verifiee" if ok else "preuve.refusee",
               {"preuve_id": proof_id, "etape_id": step["id"], "etape": step["name"], "source": source, "zone_id": zid,
                "distance_m": distance, "motifs": [I18N.render(r) for r in reasons]})
    what = L("Vidéo") if is_video else L("Preuve")
    log(p["id"], (L('%(what)s vérifiée', what=what) if ok else L('%(what)s refusée', what=what)) + L(' pour « %(name)s »', name=step['name'])
        + (L(' (inspecteur)') if source == "inspecteur" else L(' (livraison du fournisseur)') if source == "fournisseur" else ""))
    db.commit()
    if not ok:
        notify(p["id"], owners_of(p), L('Preuve refusée'), f"« {step['name']} » : " + I18N.join("; ", reasons),
               url_for("project", project_id=p["id"], onglet="preuves"), important=True)
    elif suspect:
        notify(p["id"], owners_of(p), L("Preuve à vérifier"),
               L("« %(name)s » : la photo ressemble beaucoup à une preuve déjà envoyée (même cadrage, photo d'écran ou recadrage ?). Comparez-les.",
                 name=step["name"]), url_for("project", project_id=p["id"], onglet="preuves"), important=True)
    else:
        notify(p["id"], owners_of(p), L('Nouvelle vidéo vérifiée') if is_video else L('Nouvelle preuve vérifiée'), f"« {step['name']} »",
               url_for("project", project_id=p["id"], onglet="preuves"))
    db.commit()
    if VISION.ai_enabled() and (thumb or not is_video):
        run_async(analyse_proof, proof_id)
    return ok, reasons


def analyse_proof(proof_id):
    """Analyse IA en arriere-plan : etape visible, meme chantier, signes de fraude."""
    db = connect()
    try:
        pr = db.execute("SELECT * FROM proofs WHERE id = ?", (proof_id,)).fetchone()
        steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (pr["project_id"],)).fetchall()
        step = next(s for s in steps if s["id"] == pr["step_id"])
        img = Image.open(os.path.join(UPLOAD_DIR, pr["thumb"] or pr["filename"]))
        ref = db.execute("SELECT filename, thumb FROM proofs WHERE project_id = ? AND ok = 1 AND id < ? "
                         "ORDER BY id LIMIT 1", (pr["project_id"], proof_id)).fetchone()
        ref_img = Image.open(os.path.join(UPLOAD_DIR, ref["thumb"] or ref["filename"])) if ref else None
        r = VISION.analyse_photo(img, ref_img, [s["name"] for s in steps], step["name"])
        db.execute("UPDATE proofs SET ai_status = 'ok', ai_step = ?, ai_conf = ?, ai_same_site = ?, "
                   "ai_construction = ?, ai_note = ? WHERE id = ?",
                   (r["step"], r["confidence"], None if r["same_site"] is None else int(bool(r["same_site"])),
                    int(r["construction"]), r["description"], proof_id))
        doubt = r["same_site"] is False or not r["construction"]
        db.commit()
        if doubt and pr["ok"]:
            p = db.execute("SELECT * FROM projects WHERE id = ?", (pr["project_id"],)).fetchone()
            with app.test_request_context():
                notify(p["id"], owners_of(p, db), L("Photo douteuse selon l'IA"), r["description"],
                       f"/chantiers/{p['id']}?onglet=preuves", important=True, db=db)
            db.commit()
    except Exception as e:  # l'IA ne doit jamais bloquer le chantier
        db.execute("UPDATE proofs SET ai_status = 'erreur', ai_note = ? WHERE id = ?", (str(e)[:300], proof_id))
        db.commit()
    finally:
        db.close()


@app.route("/chantiers/<int:project_id>/preuves", methods=["POST"])
@login_required
def upload_proof(project_id):
    p = load_project(project_id, roles=("chef",))
    stats = project_stats(project_id)
    step = stats["current"]
    if step is None or step["status"] != "en_cours":
        flash(_("Aucune étape en cours n'accepte de preuve."), "error")
        return redirect(url_for("project", project_id=project_id))
    ok, reasons = process_proof(p, step, current_user())
    if ok is None:
        flash(reasons, "error")
    else:
        flash(_('Preuve vérifiée et envoyée au propriétaire.') if ok
              else _('Preuve envoyée mais refusée : ') + "; ".join(map(I18N.render, reasons)), "ok" if ok else "error")
    return redirect(url_for("project", project_id=project_id))


def proof_access(pr):
    me = current_user()
    if pr["order_id"] and me["role"] == "fournisseur" and pr["user_id"] == me["id"]:
        return
    load_project(pr["project_id"], roles=("owner", "chef", "inspecteur", "admin", "intervenant"))


@app.route("/photos/<int:proof_id>")
@login_required
def proof_photo(proof_id):
    pr = get_db().execute("SELECT * FROM proofs WHERE id = ?", (proof_id,)).fetchone()
    if pr is None:
        abort(404)
    proof_access(pr)
    return send_from_directory(UPLOAD_DIR, pr["filename"])


@app.route("/photos/<int:proof_id>/vignette")
@login_required
def proof_thumb(proof_id):
    """Vignette legere (640 px) : evite de charger 200 Ko par photo sur un telephone en 3G."""
    pr = get_db().execute("SELECT * FROM proofs WHERE id = ?", (proof_id,)).fetchone()
    if pr is None:
        abort(404)
    proof_access(pr)
    if pr["thumb"]:
        return send_from_directory(UPLOAD_DIR, pr["thumb"])
    small = "v640_" + pr["filename"].rsplit(".", 1)[0] + ".jpg"
    path = os.path.join(UPLOAD_DIR, small)
    if not os.path.exists(path):
        try:
            im = Image.open(os.path.join(UPLOAD_DIR, pr["filename"])).convert("RGB")
            im.thumbnail((640, 640))
            im.save(path, "JPEG", quality=72)
        except (OSError, ValueError):
            return send_from_directory(UPLOAD_DIR, pr["filename"])
    resp = send_from_directory(UPLOAD_DIR, small)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


# --------------------------------------------------------------------------
# Etapes, paiements et sequestre
# --------------------------------------------------------------------------
def get_step(project_id, step_id):
    st = get_db().execute("SELECT * FROM steps WHERE id = ? AND project_id = ?", (step_id, project_id)).fetchone()
    if st is None:
        abort(404)
    return st


@app.route("/chantiers/<int:project_id>/etapes/<int:step_id>/declarer", methods=["POST"])
@login_required
def declare_step(project_id, step_id):
    p = load_project(project_id, roles=("chef",))
    st = get_step(project_id, step_id)
    db = get_db()
    ok_count = db.execute("SELECT COUNT(*) FROM proofs WHERE step_id = ? AND ok = 1", (step_id,)).fetchone()[0]
    if st["status"] != "en_cours" or ok_count == 0:
        flash(_("Il faut au moins une preuve vérifiée pour déclarer l'étape terminée."), "error")
    else:
        db.execute("UPDATE steps SET status = 'declare', declared_at = ? WHERE id = ?", (now_iso(), step_id))
        log(project_id, L('Étape « %(name)s » déclarée terminée', name=st['name']))
        notify(project_id, owners_of(p), L('Étape à valider'),
               L('Le chef de chantier déclare « %(name)s » terminée (%(ok_ct)s). Vérifiez avant de payer.', name=st['name'], ok_ct=ok_ct(ok_count)), url_for("project", project_id=project_id, onglet="etapes"), important=True)
        emit_event(db, project_id, "etape.declaree", {"etape_id": step_id, "etape": st["name"], "montant": st["amount"]})
        if inspection_missing(db, p, st):
            notify(project_id, owners_of(p), L("Inspection à commander"),
                   L("« %(name)s » est une étape critique : ce chantier exige une inspection indépendante avant sa validation.",
                     name=st["name"]), url_for("project", project_id=project_id, onglet="dossier", _anchor="inspections"),
                   important=True)
        seed_checks(db, project_id)
        if blocking_checks(db, step_id) and controllers_of(db, p):
            notify(project_id, controllers_of(db, p), L("Contrôle demandé"),
                   L("« %(s)s » est déclarée terminée : contrôles obligatoires à faire sur le chantier %(p)s.", s=st["name"], p=p["name"]),
                   url_for("step_page", project_id=project_id, step_id=step_id), important=True)
        db.commit()
        flash(_('Étape déclarée terminée. Le propriétaire va la vérifier.'), "ok")
    return redirect(url_for("project", project_id=project_id))


def ok_ct(n):
    return f"{n} preuve vérifiée" if n == 1 else f"{n} preuves vérifiées"


def open_next_step(db, project_id, st):
    nxt = db.execute("SELECT id FROM steps WHERE project_id = ? AND position > ? ORDER BY position LIMIT 1",
                     (project_id, st["position"])).fetchone()
    if nxt:
        db.execute("UPDATE steps SET status = 'en_cours', started_at = ? WHERE id = ? AND status = 'attente'",
                   (now_iso(), nxt["id"]))


def tx_ref(project_id):
    return f"CV{project_id}X{secrets.token_hex(5).upper()}"


def notify_url_secret():
    return hmac.new(app.config["SECRET_KEY"].encode(), b"cinetpay", "sha256").hexdigest()[:24]


@app.route("/chantiers/<int:project_id>/etapes/<int:step_id>/valider", methods=["POST"])
@login_required
def validate_step(project_id, step_id):
    p = load_project(project_id, roles=("owner",))
    st = get_step(project_id, step_id)
    db = get_db()
    back = redirect(url_for("project", project_id=project_id, onglet="etapes"))
    if st["status"] != "declare":
        flash(_("Cette étape n'est pas en attente de validation."), "error")
        return back
    if inspection_missing(db, p, st):
        flash(_("Ce chantier exige une inspection indépendante conforme avant de valider une étape critique (fondations, "
                "structure, dalle, toiture). Commandez-la dans le dossier du chantier."), "error")
        return back
    seed_checks(db, project_id)
    missing = blocking_checks(db, step_id)
    if missing and request.values.get("override") in ("1", "true", "True") and p["kind"] != "public" \
            and current_user()["id"] == p["owner_id"] and not finance_members(db, p):
        for c in missing:
            db.execute("UPDATE step_checks SET required = 0, made_optional = 1 WHERE id = ?", (c["id"],))
        log(project_id, L("Étape « %(name)s » validée sans %(n)s contrôle(s) obligatoire(s), sur décision du propriétaire",
                          name=st["name"], n=len(missing)))
        notify(project_id, [u for u in owners_of(p, db) if u != p["owner_id"]] + controllers_of(db, p),
               L("Étape validée sans contrôle"),
               L("« %(name)s » : le propriétaire a validé sans les contrôles obligatoires.", name=st["name"]),
               url_for("step_page", project_id=project_id, step_id=step_id), important=True, db=db)
        missing = []
    if missing:
        flash(_("Validation impossible : %(n)s contrôle(s) obligatoire(s) manquant(s) (%(v)s). Un contrôleur habilité doit les faire.",
                n=len(missing), v="; ".join(I18N.render(c["name"]) for c in missing[:3])), "error")
        return redirect(url_for("step_page", project_id=project_id, step_id=step_id, _anchor="controles"))
    fin = finance_members(db, p)
    me = current_user()
    if fin:
        levels = {a["level"]: a for a in step_approvals(db, step_id)}
        if me["id"] not in fin:
            if "ouvrage" in levels:
                flash(_("Étape déjà approuvée : en attente du responsable financier."), "error")
                return back
            db.execute("INSERT INTO payment_approvals (project_id, step_id, user_id, level, created_at) VALUES (?,?,?,?,?)",
                       (project_id, step_id, me["id"], "ouvrage", now_iso()))
            log(project_id, L("Étape « %(name)s » approuvée par le maître d'ouvrage, paiement à valider par le responsable financier",
                              name=st["name"]))
            notify(project_id, fin, L("Paiement à valider"),
                   L("« %(name)s » est approuvée : vérifiez et payez %(amount)s FCFA.", name=st["name"],
                     amount=f"{st['amount']:,}".replace(",", " ")),
                   url_for("step_page", project_id=project_id, step_id=step_id), important=True)
            db.commit()
            flash(_("Étape approuvée. Le responsable financier va vérifier et payer."), "ok")
            return back
        if "ouvrage" not in levels:
            flash(_("Le maître d'ouvrage doit d'abord approuver l'étape."), "error")
            return back
        if levels["ouvrage"]["user_id"] == me["id"]:
            flash(_("La même personne ne peut pas approuver et payer."), "error")
            return back
        if "finance" not in levels:
            db.execute("INSERT INTO payment_approvals (project_id, step_id, user_id, level, created_at) VALUES (?,?,?,?,?)",
                       (project_id, step_id, me["id"], "finance", now_iso()))
    if p["pay_mode"] == "sequestre":
        esc = escrow(project_id)
        if esc["balance"] < st["amount"]:
            flash(_('Solde du séquestre insuffisant : déposez au moins %(v)s FCFA.', v=format(st['amount'] - esc['balance'], ','))
                  .replace(",", " "), "error")
            return back
        chef = db.execute("SELECT * FROM users WHERE id = ?", (p["chef_id"],)).fetchone()
        if not chef or not chef["phone"]:
            flash(_('Le chef de chantier doit renseigner son numéro Mobile Money dans son compte.'), "error")
            return back
        if not release_payment(db, p, st, chef):
            return back
        emit_event(db, project_id, "etape.payee", {"etape_id": step_id, "etape": st["name"], "montant": st["amount"],
                                                   "mode": "sequestre"})
        db.commit()
    elif p["pay_mode"] == "suivi":
        if not p["chef_id"]:
            flash(_("Aucun chef de chantier : il faut un bénéficiaire pour émettre le bon à payer."), "error")
            return back
        due = payment_due(db, "etape", step_id)
        db.execute("UPDATE steps SET status = 'versement', pay_ref = ? WHERE id = ?", (due["ref"], step_id))
        log(project_id, L("Étape « %(name)s » validée : bon à payer %(ref)s de %(amount)s FCFA émis", name=st["name"],
                          ref=due["ref"], amount=fcfa_txt(st["amount"])))
        due = payment_due(db, "etape", step_id)
        pay_open_notify(db, p, due, me["id"])
        open_next_step(db, project_id, st)
        make_pv(db, p, get_step(project_id, step_id))
        emit_event(db, project_id, "etape.validee", {"etape_id": step_id, "etape": st["name"], "montant": st["amount"],
                                                     "bon_a_payer": due["ref"]})
        db.commit()
        flash(_("Étape validée. Payez %(v)s FCFA puis déclarez le paiement sur le bon à payer.", v=fcfa_txt(st["amount"])), "ok")
        if me["id"] in due["payers"] and not request.path.startswith("/api/"):
            return redirect(url_for("pay_order", kind="etape", ref_id=step_id))
        return back
    else:
        ref = request.form.get("pay_ref", "").strip()[:80]
        db.execute("UPDATE steps SET status = 'paye', paid_at = ?, pay_ref = ? WHERE id = ?", (now_iso(), ref, step_id))
        log(project_id, L('Étape « %(name)s » validée et payée', name=st['name']) + (L(' (réf. %(ref)s)', ref=ref) if ref else ""))
        notify(project_id, [p["chef_id"]], L('Étape validée'),
               L('« %(name)s » est validée. Paiement de %(amount)s FCFA', name=st['name'], amount=format(st['amount'], ',')).replace(",", " ")
               + (L(' (réf. %(ref)s).', ref=ref) if ref else "."), url_for("project", project_id=project_id), important=True)
        open_next_step(db, project_id, st)
        make_pv(db, p, get_step(project_id, step_id))
        emit_event(db, project_id, "etape.payee", {"etape_id": step_id, "etape": st["name"], "montant": st["amount"],
                                                   "mode": "manuel", "reference": ref})
        db.commit()
        flash(_("Étape validée. L'étape suivante est ouverte."), "ok")
    return back


def release_payment(db, p, st, chef):
    """Versement automatique depuis le sequestre. Retourne True si l'etape est validee."""
    prov = PAY.get_provider()
    ref = tx_ref(p["id"])
    cur = db.execute("INSERT INTO transactions (project_id, step_id, user_id, kind, amount, provider, ref, status, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (p["id"], st["id"], current_user()["id"], "versement", st["amount"], prov.name, ref,
                      "en_attente", now_iso(), now_iso()))
    tid = cur.lastrowid
    db.commit()
    try:
        r = prov.payout(ref, st["amount"], chef["phone"], chef["name"],
                        public_url(url_for("cinetpay_notify", secret=notify_url_secret())) or "")
    except Exception as e:
        r = {"status": "echoue", "error": str(e)[:200]}
    db.execute("UPDATE transactions SET status = ?, provider_ref = ?, error = ?, updated_at = ? WHERE id = ?",
               (r["status"], r.get("provider_ref"), r.get("error"), now_iso(), tid))
    if r["status"] == "echoue":
        log(p["id"], L('Versement échoué pour « %(name)s » : %(v)s', name=st['name'], v=r.get('error')))
        db.commit()
        flash(_('Le versement a échoué : ') + (r.get("error") or "erreur inconnue") + _(". L'étape reste à valider."),
              "error")
        return False
    status = "paye" if r["status"] == "reussi" else "versement"
    db.execute("UPDATE steps SET status = ?, paid_at = ?, pay_ref = ? WHERE id = ?",
               (status, now_iso() if status == "paye" else None, r.get("provider_ref") or ref, st["id"]))
    sim = " (simulation)" if not prov.real else ""
    log(p["id"], L('Étape « %(name)s » validée, %(amount)s FCFA ', name=st['name'], amount=format(st['amount'], ',')).replace(",", " ")
        + (L('versés') if status == "paye" else L('en cours de versement')) + L(' depuis le séquestre%(sim)s', sim=sim))
    notify(p["id"], [p["chef_id"]], L('Paiement envoyé') if status == "paye" else L('Paiement en cours'),
           L('« %(name)s » validée : %(amount)s FCFA vers votre Mobile Money%(sim)s.', name=st['name'], amount=format(st['amount'], ','), sim=sim).replace(",", " "),
           url_for("project", project_id=p["id"]), important=True)
    open_next_step(db, p["id"], st)
    make_pv(db, p, get_step(p["id"], st["id"]))
    db.commit()
    flash(_('Étape validée. %(amount)s FCFA ', amount=format(st['amount'], ',')).replace(",", " ")
          + (_('versés au chef de chantier') if status == "paye" else _('en cours de versement')) + f"{sim}.", "ok")
    return True


@app.route("/chantiers/<int:project_id>/etapes/<int:step_id>/refuser", methods=["POST"])
@login_required
def refuse_step(project_id, step_id):
    p = load_project(project_id, roles=("owner",))
    st = get_step(project_id, step_id)
    if st["status"] == "declare":
        db = get_db()
        db.execute("UPDATE steps SET status = 'en_cours', declared_at = NULL WHERE id = ?", (step_id,))
        db.execute("DELETE FROM payment_approvals WHERE step_id = ?", (step_id,))
        motif = request.form.get("motif", "").strip()[:200]
        log(project_id, L('Étape « %(name)s » refusée', name=st['name']) + (f" : {motif}" if motif else ""))
        notify(project_id, [p["chef_id"]], L('Étape refusée'),
               L('« %(name)s » renvoyée', name=st['name']) + (f" : {motif}" if motif else ".") + L(' Envoyez de nouvelles preuves.'),
               url_for("project", project_id=project_id), important=True)
        db.commit()
        flash(_('Étape renvoyée au chef de chantier.'), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="etapes"))


@app.route("/chantiers/<int:project_id>/paiements/mode", methods=["POST"])
@login_required
def set_pay_mode(project_id):
    p = load_project(project_id, roles=("owner",))
    mode = allowed_pay_mode(request.form.get("pay_mode"), p["pay_mode"], fallback=p["pay_mode"])
    db = get_db()
    if p["pay_mode"] == "sequestre" and mode != "sequestre" and escrow(project_id, db)["balance"] > 0:
        flash(_("Il reste %(v)s FCFA sur le séquestre : ils servent d'abord à payer les étapes suivantes.",
                v=fcfa_txt(escrow(project_id, db)["balance"])), "error")
        return redirect(url_for("project", project_id=project_id, onglet="etapes"))
    db.execute("UPDATE projects SET pay_mode = ? WHERE id = ?", (mode, project_id))
    log(project_id, L('Mode de paiement : ') + PAY_MODE_LOG[mode])
    db.commit()
    return redirect(url_for("project", project_id=project_id, onglet="etapes"))


# --------------------------------------------------------------------------
# Paiement suivi : ChantierVrai enregistre chaque paiement sans toucher l'argent.
# Bon a payer -> le payeur paie hors plateforme et declare (reference, recu)
# -> le beneficiaire confirme la reception ou conteste.
# --------------------------------------------------------------------------
PAY_MODES = {"suivi": "Paiement suivi : je paie moi-même, ChantierVrai enregistre et le bénéficiaire confirme",
             "manuel": "Simple : je valide et je note la référence",
             "sequestre": "Séquestre : versement automatique à chaque validation"}
PAY_MODE_LOG = {"suivi": L("paiement suivi (hors plateforme, confirmé par le bénéficiaire)"),
                "manuel": L("paiement manuel"), "sequestre": L("séquestre (versement automatique)")}
PAY_METHODS = {"mobile_money": "Mobile Money", "virement": "Virement bancaire", "especes": "Espèces (avec reçu signé)",
               "cheque": "Chèque", "autre": "Autre"}
PAY_KINDS = {"etape": "Étape", "commande": "Commande de matériaux", "inspection": "Inspection"}
PAY_REC_STATUS = {"declare": "Déclaré, en attente de confirmation", "confirme": "Reçu, confirmé par le bénéficiaire",
                  "conteste": "Contesté par le bénéficiaire"}
RECEIPT_EXT = {"pdf", "jpg", "jpeg", "png", "webp"}
RECEIPT_MAX = 10 * 1024 * 1024
REMIND_AFTER_DAYS = 3


def fcfa_txt(n):
    return f"{int(round(n or 0)):,}".replace(",", " ")


def get_setting(key, default=None, db=None):
    db = db or get_db()
    r = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(db, key, value, uid=None):
    if db.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone():
        db.execute("UPDATE settings SET value = ?, updated_by = ?, updated_at = ? WHERE key = ?", (value, uid, now_iso(), key))
    else:
        db.execute("INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?,?,?,?)", (key, value, uid, now_iso()))


def escrow_enabled(db=None):
    """Sequestre ouvert aux nouveaux depots ? Desactive par defaut ; seul le super-admin l'active."""
    v = app.config.get("ESCROW_ENABLED")
    if v is not None:
        return bool(v)
    return get_setting("escrow_enabled", "0", db) == "1"


def allowed_pay_mode(requested, current=None, fallback="suivi"):
    """Sequestre seulement s'il est active (ou deja en place sur le chantier) ; sinon paiement suivi."""
    if requested == "sequestre":
        return "sequestre" if (escrow_enabled() or current == "sequestre") else "suivi"
    return requested if requested in ("suivi", "manuel") else fallback


def payment_due(db, kind, ref_id):
    """Ce qui est du, a qui, par qui. Retourne None si l'element n'existe pas."""
    if kind == "etape":
        st = db.execute("SELECT * FROM steps WHERE id = ?", (ref_id,)).fetchone()
        if not st:
            return None
        p = db.execute("SELECT * FROM projects WHERE id = ?", (st["project_id"],)).fetchone()
        due = dict(item=st, amount=st["amount"], payee_id=p["chef_id"], label=L("Étape « %(name)s »", name=st["name"]),
                   open=st["status"] == "versement" and p["pay_mode"] in ("suivi", "manuel"), done=st["status"] == "paye",
                   back=url_for("step_page", project_id=p["id"], step_id=st["id"]))
    elif kind == "commande":
        o = db.execute("SELECT * FROM orders WHERE id = ?", (ref_id,)).fetchone()
        if not o:
            return None
        p = db.execute("SELECT * FROM projects WHERE id = ?", (o["project_id"],)).fetchone()
        due = dict(item=o, amount=o["received_total"] if o["received_total"] is not None else o["total"],
                   payee_id=o["supplier_id"], label=L("Commande de matériaux %(ref)s", ref=o["ref"]),
                   open=o["status"] == "a_payer" and o["pay_mode"] == "suivi", done=o["status"] == "receptionnee",
                   back=url_for("order", oid=o["id"]))
    elif kind == "inspection":
        i = db.execute("SELECT * FROM inspections WHERE id = ?", (ref_id,)).fetchone()
        if not i:
            return None
        p = db.execute("SELECT * FROM projects WHERE id = ?", (i["project_id"],)).fetchone()
        due = dict(item=i, amount=i["fee"] or 0, payee_id=i["inspector_id"], label=L("Inspection indépendante"),
                   open=i["status"] == "realisee" and bool(i["fee"]) and not i["paid"] and not i["sold"]
                   and p["pay_mode"] == "suivi",
                   done=bool(i["paid"]), back=url_for("project", project_id=p["id"], onglet="dossier", _anchor="inspections"))
    else:
        return None
    fin = finance_members(db, p)
    due.update(kind=kind, ref_id=ref_id, project=p, payers=fin or owners_of(p, db))
    recs = db.execute("SELECT r.*, u.name AS payer_name FROM payment_records r LEFT JOIN users u ON u.id = r.payer_id "
                      "WHERE kind = ? AND ref_id = ? ORDER BY r.id", (kind, ref_id)).fetchall()
    due["records"] = recs
    due["confirmed"] = sum(r["amount"] for r in recs if r["status"] == "confirme")
    due["declared"] = sum(r["amount"] for r in recs if r["status"] == "declare")
    due["remaining"] = max(due["amount"] - due["confirmed"] - due["declared"], 0)
    due["ref"] = f"BAP-{p['id']}-{kind[0].upper()}{ref_id}"
    due["code"] = hmac.new(app.config["SECRET_KEY"].encode(), f"{due['ref']}|{due['amount']}".encode(),
                           "sha256").hexdigest()[:10].upper()
    return due


def pay_access(due, user):
    """payer, beneficiaire, proprietaires, comptable du chantier, ou equipe autorisee."""
    if not user:
        return None
    p = due["project"]
    if user["id"] in due["payers"]:
        return "payer"
    if user["id"] == due["payee_id"]:
        return "payee"
    if user["id"] in owners_of(p):
        return "owner"
    db = get_db()
    m = db.execute("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?", (p["id"], user["id"])).fetchone()
    if m and "finances" in MEMBER_RIGHTS.get(m["role"], set()):
        return "viewer"
    if can("projects", user):
        return "viewer"
    return None


def pay_open_notify(db, p, due, me_id=None):
    """Bon a payer emis : le payeur est prevenu, le beneficiaire sait que le paiement arrive."""
    notify(p["id"], [u for u in due["payers"] if u != me_id], L("Bon à payer"),
           L("%(label)s : payez %(amount)s FCFA à %(who)s, puis déclarez le paiement avec la référence ou le reçu.",
             label=due["label"], amount=fcfa_txt(due["amount"]), who=user_name(db, due["payee_id"])),
           url_for("pay_order", kind=due["kind"], ref_id=due["ref_id"]), important=True, db=db)
    if due["payee_id"]:
        notify(p["id"], [due["payee_id"]], L("Paiement à venir"),
               L("%(label)s est validé : %(amount)s FCFA vont vous être payés. Confirmez dans ChantierVrai quand vous les recevez.",
                 label=due["label"], amount=fcfa_txt(due["amount"])), url_for("payments_received"), important=True, db=db)


def user_name(db, uid):
    r = db.execute("SELECT name FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
    return r["name"] if r else "?"


def finalize_payment(db, due, me):
    """Tout le montant est confirme par le beneficiaire : l'element passe a paye."""
    p, refs = due["project"], ", ".join(r["reference"] for r in due["records"] if r["status"] == "confirme" and r["reference"])
    refs = refs[:200] or None
    if due["kind"] == "etape":
        db.execute("UPDATE steps SET status = 'paye', paid_at = ?, pay_ref = COALESCE(?, pay_ref) WHERE id = ?",
                   (now_iso(), refs, due["ref_id"]))
        emit_event(db, p["id"], "etape.payee", {"etape_id": due["ref_id"], "etape": due["item"]["name"],
                                                "montant": due["amount"], "mode": "suivi", "reference": refs})
    elif due["kind"] == "commande":
        set_order(db, due["ref_id"], status="receptionnee", pay_ref=refs)
    elif due["kind"] == "inspection":
        db.execute("UPDATE inspections SET paid = 1, pay_ref = ? WHERE id = ?", (refs or "suivi", due["ref_id"]))
    log(p["id"], L("%(label)s : paiement de %(amount)s FCFA confirmé par le bénéficiaire", label=due["label"],
                   amount=fcfa_txt(due["amount"])), db, me["id"])


@app.route("/paiements/<kind>/<int:ref_id>", methods=["GET", "POST"])
@login_required
def pay_order(kind, ref_id):
    """Bon a payer (imprimable) et declaration du paiement par le payeur."""
    db = get_db()
    due = payment_due(db, kind, ref_id)
    if due is None:
        abort(404)
    me = current_user()
    access = pay_access(due, me)
    if not access:
        abort(403)
    p = due["project"]
    back = redirect(url_for("pay_order", kind=kind, ref_id=ref_id))
    if request.method == "POST":
        if access != "payer":
            abort(403)
        if not due["open"]:
            flash(_("Ce paiement n'est pas à déclarer."), "error")
            return back
        f = request.form
        amount = int(to_float((f.get("amount") or "").replace(" ", "")) or 0)
        method = f.get("method")
        reference = f.get("reference", "").strip()[:80]
        paid_on = f.get("paid_on") or now_iso()[:10]
        try:
            date.fromisoformat(paid_on)
        except ValueError:
            paid_on = now_iso()[:10]
        file = request.files.get("receipt")
        has_file = bool(file and file.filename)
        if method not in PAY_METHODS or amount <= 0:
            flash(_("Indiquez le montant payé et le moyen de paiement."), "error")
            return back
        if amount > due["remaining"]:
            flash(_("Montant trop élevé : il reste %(v)s FCFA à payer.", v=fcfa_txt(due["remaining"])), "error")
            return back
        if not reference and not has_file:
            flash(_("Ajoutez la référence de la transaction ou le reçu : c'est ce que le bénéficiaire vérifie."), "error")
            return back
        name = sha = orig = None
        if has_file:
            if ext_of(file.filename) not in RECEIPT_EXT:
                flash(_("Reçu : PDF ou photo (JPEG, PNG)."), "error")
                return back
            raw = file.read()
            if len(raw) > RECEIPT_MAX:
                flash(_("Reçu trop lourd (10 Mo maximum)."), "error")
                return back
            name = f"recu-{secrets.token_hex(12)}.{ext_of(file.filename)}"
            with open(os.path.join(DOC_DIR, name), "wb") as fh:
                fh.write(raw)
            sha, orig = hashlib.sha256(raw).hexdigest(), file.filename[:150]
        rid = db.execute("INSERT INTO payment_records (project_id, kind, ref_id, payer_id, payee_id, amount, method, reference, "
                         "paid_on, receipt, receipt_name, receipt_sha, note, status, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (p["id"], kind, ref_id, me["id"], due["payee_id"], amount, method, reference or None, paid_on,
                          name, orig, sha, f.get("note", "").strip()[:300] or None, "declare", now_iso())).lastrowid
        log(p["id"], L("%(label)s : paiement de %(amount)s FCFA déclaré (%(m)s%(ref)s), en attente de confirmation",
                       label=due["label"], amount=fcfa_txt(amount), m=L(PAY_METHODS[method]),
                       ref=f", réf. {reference}" if reference else ""), db, me["id"])
        if due["payee_id"]:
            notify(p["id"], [due["payee_id"]], L("Paiement à confirmer"),
                   L("%(who)s déclare vous avoir payé %(amount)s FCFA (%(label)s). Confirmez la réception ou signalez un problème.",
                     who=me["name"], amount=fcfa_txt(amount), label=due["label"]), url_for("payments_received"),
                   important=True, db=db)
        emit_event(db, p["id"], "paiement.declare", {"paiement_id": rid, "objet": kind, "objet_id": ref_id,
                                                     "montant": amount, "moyen": method, "reference": reference or None})
        db.commit()
        flash(_("Paiement déclaré. Le bénéficiaire doit maintenant confirmer la réception."), "ok")
        return back
    payee = db.execute("SELECT id, name, phone, company FROM users WHERE id = ?", (due["payee_id"],)).fetchone() \
        if due["payee_id"] else None
    approvals = []
    if kind == "etape":
        approvals = db.execute("SELECT a.*, u.name FROM payment_approvals a JOIN users u ON u.id = a.user_id WHERE step_id = ? "
                               "ORDER BY a.id", (ref_id,)).fetchall()
    proofs_ok = db.execute("SELECT COUNT(*) FROM proofs WHERE step_id = ? AND ok = 1", (ref_id,)).fetchone()[0] \
        if kind == "etape" else None
    return render_template("pay_order.html", due=due, p=p, access=access, payee=payee, approvals=approvals,
                           proofs_ok=proofs_ok, PAY_METHODS=tr(PAY_METHODS), PAY_REC_STATUS=tr(PAY_REC_STATUS),
                           today=now_iso()[:10])


@app.route("/paiements/recus", methods=["GET"])
@login_required
def payments_received():
    """Paiements declares en faveur de l'utilisateur : a confirmer, puis historique."""
    db = get_db()
    rows = db.execute("SELECT r.*, p.name AS project_name, u.name AS payer_name FROM payment_records r JOIN projects p ON "
                      "p.id = r.project_id LEFT JOIN users u ON u.id = r.payer_id WHERE r.payee_id = ? "
                      "ORDER BY r.status = 'declare' DESC, r.id DESC LIMIT 200", (current_user()["id"],)).fetchall()
    items = []
    for r in rows:
        due = payment_due(db, r["kind"], r["ref_id"])
        items.append((r, due["label"] if due else ""))
    return render_template("payments_received.html", items=items, PAY_METHODS=tr(PAY_METHODS),
                           PAY_REC_STATUS=tr(PAY_REC_STATUS))


@app.route("/paiements/recus/<int:rid>", methods=["POST"])
@login_required
def payment_answer(rid):
    """Le beneficiaire confirme avoir recu l'argent, ou conteste."""
    db = get_db()
    r = db.execute("SELECT * FROM payment_records WHERE id = ?", (rid,)).fetchone()
    if r is None:
        abort(404)
    me = current_user()
    if r["payee_id"] != me["id"]:
        abort(403)
    back = redirect(url_for("payments_received"))
    if r["status"] != "declare":
        flash(_("Ce paiement a déjà reçu une réponse."), "error")
        return back
    due = payment_due(db, r["kind"], r["ref_id"])
    p = due["project"]
    action = request.form.get("action")
    if action == "confirm":
        db.execute("UPDATE payment_records SET status = 'confirme', answered_at = ? WHERE id = ?", (now_iso(), rid))
        log(p["id"], L("%(who)s confirme avoir reçu %(amount)s FCFA (%(label)s)", who=me["name"], amount=fcfa_txt(r["amount"]),
                       label=due["label"]), db, me["id"])
        notify(p["id"], [r["payer_id"]], L("Paiement confirmé"),
               L("%(who)s confirme avoir reçu %(amount)s FCFA (%(label)s).", who=me["name"], amount=fcfa_txt(r["amount"]),
                 label=due["label"]), url_for("pay_order", kind=r["kind"], ref_id=r["ref_id"]), db=db)
        emit_event(db, p["id"], "paiement.confirme", {"paiement_id": rid, "objet": r["kind"], "objet_id": r["ref_id"],
                                                      "montant": r["amount"]})
        due = payment_due(db, r["kind"], r["ref_id"])
        if due["confirmed"] >= due["amount"] and not due["done"]:
            finalize_payment(db, due, me)
        flash(_("Réception confirmée. Merci."), "ok")
    elif action == "contest":
        text = request.form.get("text", "").strip()[:500]
        if len(text) < 10:
            flash(_("Expliquez le problème (10 caractères minimum) : montant différent, rien reçu…"), "error")
            return back
        db.execute("UPDATE payment_records SET status = 'conteste', contest_note = ?, answered_at = ? WHERE id = ?",
                   (text, now_iso(), rid))
        log(p["id"], L("%(who)s conteste le paiement de %(amount)s FCFA (%(label)s) : %(v)s", who=me["name"],
                       amount=fcfa_txt(r["amount"]), label=due["label"], v=text), db, me["id"])
        notify(p["id"], list({r["payer_id"], *owners_of(p, db)}), L("Paiement contesté"),
               L("%(who)s n'a pas reçu %(amount)s FCFA comme déclaré (%(label)s) : %(v)s", who=me["name"],
                 amount=fcfa_txt(r["amount"]), label=due["label"], v=text),
               url_for("pay_order", kind=r["kind"], ref_id=r["ref_id"]), important=True, db=db)
        emit_event(db, p["id"], "paiement.conteste", {"paiement_id": rid, "objet": r["kind"], "objet_id": r["ref_id"],
                                                      "montant": r["amount"], "motif": text})
        flash(_("Problème signalé au payeur. Le montant redevient à payer ; ouvrez un litige si vous ne trouvez pas d'accord."),
              "ok")
    else:
        abort(400)
    db.commit()
    return back


@app.route("/paiements/recu/<int:rid>/fichier")
@login_required
def payment_receipt(rid):
    db = get_db()
    r = db.execute("SELECT * FROM payment_records WHERE id = ?", (rid,)).fetchone()
    if r is None or not r["receipt"]:
        abort(404)
    due = payment_due(db, r["kind"], r["ref_id"])
    if not pay_access(due, current_user()):
        abort(403)
    return send_from_directory(DOC_DIR, r["receipt"], download_name=r["receipt_name"] or r["receipt"],
                               as_attachment=ext_of(r["receipt"]) not in ("pdf", "jpg", "jpeg", "png", "webp"))


def project_payments(db, p):
    """Tous les paiements suivis du chantier : etapes validees, commandes recues, inspections realisees."""
    out = []
    for st in db.execute("SELECT id FROM steps WHERE project_id = ? AND status IN ('versement', 'paye') ORDER BY position",
                         (p["id"],)):
        out.append(payment_due(db, "etape", st["id"]))
    for o in db.execute("SELECT id FROM orders WHERE project_id = ? AND status IN ('a_payer', 'receptionnee') ORDER BY id",
                        (p["id"],)):
        out.append(payment_due(db, "commande", o["id"]))
    for i in db.execute("SELECT id FROM inspections WHERE project_id = ? AND status = 'realisee' AND fee > 0 AND sold = 0 "
                        "ORDER BY id",
                        (p["id"],)):
        out.append(payment_due(db, "inspection", i["id"]))
    return out


@app.route("/chantiers/<int:project_id>/paiements")
@login_required
def payments_ledger(project_id):
    """Registre des paiements : du, declare, confirme, reste, avec les recus. Export CSV."""
    p = load_project(project_id, roles=("owner", "chef", "intervenant", "admin"))
    if g.project_role == "intervenant" and not member_can("finances"):
        abort(403)
    db = get_db()
    dues = project_payments(db, p)
    if g.project_role == "chef":
        dues = [d for d in dues if d["payee_id"] == current_user()["id"]]
    tot = {k: sum(d[k] for d in dues) for k in ("amount", "confirmed", "declared")}
    tot["remaining"] = sum(max(d["amount"] - d["confirmed"], 0) for d in dues if not d["done"])
    tot["contested"] = sum(1 for d in dues for r in d["records"] if r["status"] == "conteste")
    if request.args.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow([_("Bon à payer"), _("Objet"), _("Bénéficiaire"), _("Montant dû (FCFA)"), _("Date du paiement"),
                    _("Montant payé (FCFA)"), _("Moyen"), _("Référence"), _("Statut"), _("Reçu (empreinte SHA-256)")])
        for d in dues:
            if not d["records"]:
                w.writerow([d["ref"], I18N.render(d["label"]), user_name(db, d["payee_id"]), d["amount"], "", "", "", "",
                            _("À payer"), ""])
            for r in d["records"]:
                w.writerow([d["ref"], I18N.render(d["label"]), user_name(db, d["payee_id"]), d["amount"], r["paid_on"],
                            r["amount"], _(PAY_METHODS[r["method"]]), r["reference"] or "", _(PAY_REC_STATUS[r["status"]]),
                            r["receipt_sha"] or ""])
        resp = app.response_class("﻿" + out.getvalue(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f'attachment; filename="chantier-{project_id}-paiements.csv"'
        return resp
    names = {d["payee_id"]: user_name(db, d["payee_id"]) for d in dues}
    return render_template("payments.html", p=p, dues=dues, tot=tot, names=names, role=g.project_role,
                           PAY_METHODS=tr(PAY_METHODS), PAY_REC_STATUS=tr(PAY_REC_STATUS), PAY_KINDS=tr(PAY_KINDS))


AUTO_VALIDATE_DAYS = 7          # delai par defaut, reglable par le super-admin (5 a 30 jours)
CRITICAL_WORDS = ("fondation", "semelle", "structure", "elevation", "élévation", "poteau", "dalle", "plancher",
                  "charpente", "toiture")


def auto_validate_on(db=None):
    """Validation automatique proposee sur la plateforme ? Desactivee par defaut ; le super-admin l'active."""
    return get_setting("auto_validate_enabled", "0", db) == "1"


def auto_validate_days(db=None):
    return min(max(to_int(get_setting("auto_validate_days", str(AUTO_VALIDATE_DAYS), db)) or AUTO_VALIDATE_DAYS, 5), 30)


def owner_remind_days(n):
    """Relances du proprietaire : a J+2, puis 3 jours et 1 jour avant la validation automatique."""
    return sorted({2, max(n - 3, 3), n - 1})


def is_critical(step_name):
    name = (step_name or "").lower()
    return any(w in name for w in CRITICAL_WORDS)


def inspection_missing(db, p, st):
    """Inspection obligatoire non faite sur une etape critique (chantier qui l'exige)."""
    if not p["require_inspection"] or not is_critical(st["name"]):
        return False
    last = db.execute("SELECT verdict FROM inspections WHERE step_id = ? AND status = 'realisee' ORDER BY id DESC LIMIT 1",
                      (st["id"],)).fetchone()
    return last is None or last["verdict"] == "non_conforme"


def auto_validate_steps(db):
    """Etape declaree terminee sans reponse du proprietaire. Relances explicites dans tous les cas (J+2, puis
    3 jours et 1 jour avant l'echeance). Validation automatique seulement si la plateforme la propose ET que le
    proprietaire l'a acceptee sur ce chantier ; jamais sans les controles obligatoires, l'inspection exigee ou
    avec un litige ouvert. Sinon, a l'echeance, le chef est invite a ouvrir un litige."""
    now = datetime.now(timezone.utc)
    enabled, n_days = auto_validate_on(db), auto_validate_days(db)
    out = {"relances": 0, "validees": 0, "bloquees": 0, "arbitrage": 0}
    rows = db.execute("SELECT * FROM steps WHERE status = 'declare' AND declared_at IS NOT NULL").fetchall()
    for st in rows:
        p = db.execute("SELECT * FROM projects WHERE id = ?", (st["project_id"],)).fetchone()
        auto = enabled and bool(p["auto_validate"]) and p["pay_mode"] != "sequestre" and bool(p["chef_id"])
        declared = datetime.fromisoformat(st["declared_at"])
        days = (now - declared).days
        payers = finance_members(db, p) or owners_of(p, db)
        due_day = format_d((declared + timedelta(days=n_days)).isoformat())
        step_url = url_for("step_page", project_id=p["id"], step_id=st["id"])
        if days < n_days:
            n = sum(1 for d in owner_remind_days(n_days) if days >= d)
            if n > st["owner_reminders"]:
                if auto:
                    text = L("« %(name)s » attend votre réponse depuis %(n)s jour(s). Sans validation ni refus, elle sera validée "
                             "automatiquement le %(d)s et le bon à payer sera émis, comme vous l'avez accepté pour ce chantier. "
                             "Si vous n'êtes pas d'accord, refusez l'étape ou ouvrez un litige avant cette date.",
                             name=st["name"], n=days, d=due_day)
                else:
                    text = L("« %(name)s » attend votre réponse depuis %(n)s jour(s). Le chef de chantier attend votre décision "
                             "pour être payé : validez ou refusez avec un motif.", name=st["name"], n=days)
                notify(p["id"], payers, L("Étape à valider"), text, step_url, important=True, db=db)
                db.execute("UPDATE steps SET owner_reminders = ? WHERE id = ?", (n, st["id"]))
                out["relances"] += 1
            continue
        if st["owner_reminders"] >= 9:          # deja traitee (bloquee, ou chef invite au litige)
            continue
        if db.execute("SELECT 1 FROM disputes WHERE project_id = ? AND step_id = ? AND status IN ('ouvert', 'en_appel')",
                      (p["id"], st["id"])).fetchone():
            continue
        if not auto:
            notify(p["id"], [p["chef_id"]] if p["chef_id"] else [], L("Sans réponse du propriétaire"),
                   L("« %(name)s » attend la réponse du propriétaire depuis %(n)s jours. Vous pouvez ouvrir un litige : la "
                     "médiation ChantierVrai tranchera.", name=st["name"], n=days), step_url, important=True, db=db)
            if p["pay_mode"] == "sequestre":
                notify(p["id"], admins(db, "disputes"), L("Arbitrage demandé"),
                       L("« %(name)s » (%(p)s) attend la réponse du propriétaire depuis %(n)s jours.", name=st["name"],
                         p=p["name"], n=days), step_url, db=db)
            db.execute("UPDATE steps SET owner_reminders = 9 WHERE id = ?", (st["id"],))
            out["arbitrage"] += 1
            continue
        seed_checks(db, p["id"])
        missing = blocking_checks(db, st["id"])
        no_insp = inspection_missing(db, p, st)
        if missing or no_insp:
            notify(p["id"], [p["chef_id"]] + payers, L("Validation automatique impossible"),
                   (L("« %(name)s » : %(n)s contrôle(s) obligatoire(s) manquent encore. Ils doivent être faits avant toute validation.",
                      name=st["name"], n=len(missing)) if missing else
                    L("« %(name)s » : l'inspection indépendante exigée sur ce chantier n'est pas faite ou n'est pas conforme.",
                      name=st["name"])), step_url, important=True, db=db)
            db.execute("UPDATE steps SET owner_reminders = 9 WHERE id = ?", (st["id"],))
            out["bloquees"] += 1
            continue
        due = payment_due(db, "etape", st["id"])
        db.execute("UPDATE steps SET status = 'versement', pay_ref = ?, auto_validated = 1 WHERE id = ?", (due["ref"], st["id"]))
        log(p["id"], L("Étape « %(name)s » validée automatiquement : pas de réponse du propriétaire en %(n)s jours",
                       name=st["name"], n=n_days), db, p["chef_id"])
        due = payment_due(db, "etape", st["id"])
        pay_open_notify(db, p, due)
        notify(p["id"], payers, L("Étape validée automatiquement"),
               L("« %(name)s » était déclarée terminée depuis %(n)s jours sans réponse. Le bon à payer est émis ; en cas de désaccord, ouvrez un litige.",
                 name=st["name"], n=days), url_for("pay_order", kind="etape", ref_id=st["id"]), important=True, db=db)
        open_next_step(db, p["id"], st)
        make_pv(db, p, db.execute("SELECT * FROM steps WHERE id = ?", (st["id"],)).fetchone())
        emit_event(db, p["id"], "etape.validee", {"etape_id": st["id"], "etape": st["name"], "montant": st["amount"],
                                                  "bon_a_payer": due["ref"], "automatique": True})
        out["validees"] += 1
    db.commit()
    return out


DISPUTE_RESPOND_DAYS = 5        # echanges entre les parties avant la mediation
DISPUTE_DECIDE_DAYS = 10        # delai de decision de la mediation
DISPUTE_APPEAL_DAYS = 7         # delai de recours apres la decision
DISPUTE_OUTCOMES = {"chef": "En faveur du chef de chantier", "proprietaire": "En faveur du propriétaire",
                    "partage": "Torts partagés", "recommandation": "Recommandation sans attribution"}
DISPUTE_STAGES = {"echanges": "Échanges entre les parties", "mediation": "Médiation ChantierVrai",
                  "resolu": "Décision rendue", "en_appel": "Recours en cours", "clos": "Clos"}


def disputes_daily(db):
    """Fait avancer les litiges : mediation apres 5 jours, alerte si la decision tarde, cloture apres le delai de recours."""
    now = datetime.now(timezone.utc)
    out = {"mediation": 0, "en_retard": 0, "clos": 0}
    for d in db.execute("SELECT * FROM disputes WHERE status IN ('ouvert', 'resolu')").fetchall():
        p = db.execute("SELECT * FROM projects WHERE id = ?", (d["project_id"],)).fetchone()
        if d["status"] == "ouvert" and d["stage"] == "echanges" and d["respond_by"] and datetime.fromisoformat(d["respond_by"]) <= now:
            decide = (now + timedelta(days=DISPUTE_DECIDE_DAYS)).isoformat()
            db.execute("UPDATE disputes SET stage = 'mediation', decide_by = ? WHERE id = ?", (decide, d["id"]))
            _p, parties = dispute_parties(db, d)
            notify(p["id"], parties + admins(db, "disputes"), L("Litige en médiation"),
                   L("« %(s)s » : pas d'accord en %(n)s jours. La médiation ChantierVrai décide avant le %(d)s.",
                     s=d["subject"], n=DISPUTE_RESPOND_DAYS, d=format_d(decide)), url_for("dispute", did=d["id"]),
                   important=True, db=db)
            out["mediation"] += 1
        elif d["status"] == "ouvert" and d["stage"] == "mediation" and d["decide_by"] and not d["escalated"] \
                and datetime.fromisoformat(d["decide_by"]) <= now:
            notify(p["id"], admins(db, "platform"), L("Litige : décision en retard"),
                   L("« %(s)s » (%(p)s) attend une décision depuis le %(d)s.", s=d["subject"], p=p["name"],
                     d=format_d(d["decide_by"])), url_for("dispute", did=d["id"]), important=True, db=db)
            db.execute("UPDATE disputes SET escalated = 1 WHERE id = ?", (d["id"],))
            out["en_retard"] += 1
        elif d["status"] == "resolu" and (not d["appeal_until"] or datetime.fromisoformat(d["appeal_until"]) <= now):
            db.execute("UPDATE disputes SET status = 'clos', stage = 'clos' WHERE id = ?", (d["id"],))
            out["clos"] += 1
    db.commit()
    return out


SIG_ANSWER_DAYS = 10            # le maitre d'ouvrage repond publiquement sous 10 jours
SIG_STATUS = {"nouveau": "Reçu", "en_cours": "Pris en charge", "traite": "Traité, réponse publiée",
              "rejete": "Écarté par la modération"}


def signalements_daily(db):
    """Signalement citoyen sans reponse : rappel au maitre d'ouvrage a J+5, puis au support a J+10."""
    now = datetime.now(timezone.utc)
    out = {"rappels": 0, "support": 0}
    for sg in db.execute("SELECT * FROM signalements WHERE status IN ('nouveau', 'en_cours') AND hidden = 0").fetchall():
        p = db.execute("SELECT * FROM projects WHERE id = ?", (sg["project_id"],)).fetchone()
        days = (now - datetime.fromisoformat(sg["created_at"])).days
        if days >= SIG_ANSWER_DAYS and sg["reminded"] < 2:
            notify(p["id"], admins(db, "moderation"), L("Signalement citoyen sans réponse"),
                   L("%(p)s : signalement reçu il y a %(n)s jours, toujours sans réponse publique.", p=p["name"], n=days),
                   "/admin#moderation", db=db)
            db.execute("UPDATE signalements SET reminded = 2 WHERE id = ?", (sg["id"],))
            out["support"] += 1
        elif days >= SIG_ANSWER_DAYS // 2 and sg["reminded"] < 1:
            notify(p["id"], owners_of(p, db), L("Signalement citoyen à traiter"),
                   L("Un habitant attend votre réponse depuis %(n)s jours. Répondez avant %(m)s jours : la réponse est publiée sur le portail.",
                     n=days, m=SIG_ANSWER_DAYS), url_for("project", project_id=p["id"], onglet="dossier", _anchor="signalements"),
                   important=True, db=db)
            db.execute("UPDATE signalements SET reminded = 1 WHERE id = ?", (sg["id"],))
            out["rappels"] += 1
    db.commit()
    return out


def remind_payments(db):
    """Relance le beneficiaire qui n'a pas confirme un paiement declare depuis 3 jours."""
    limit = (datetime.now(timezone.utc) - timedelta(days=REMIND_AFTER_DAYS)).isoformat()
    n = 0
    for r in db.execute("SELECT * FROM payment_records WHERE status = 'declare' AND created_at < ? AND "
                        "(reminded_at IS NULL OR reminded_at < ?)", (limit, limit)).fetchall():
        due = payment_due(db, r["kind"], r["ref_id"])
        notify(r["project_id"], [r["payee_id"]], L("Paiement à confirmer"),
               L("%(amount)s FCFA déclarés le %(d)s (%(label)s) : confirmez la réception ou signalez un problème.",
                 amount=fcfa_txt(r["amount"]), d=r["paid_on"], label=due["label"]), "/paiements/recus", important=True, db=db)
        db.execute("UPDATE payment_records SET reminded_at = ? WHERE id = ?", (now_iso(), r["id"]))
        n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------
# Abonnements ChantierVrai : c'est ainsi que la plateforme est payee par ses clients.
# Essai gratuit -> offre payante -> facture -> paiement -> renouvellement, relances, suspension.
# Un abonnement suspendu bloque seulement les nouveaux chantiers et les options payantes :
# les chantiers existants, les preuves et les paiements continuent (on ne prend pas les donnees en otage).
# --------------------------------------------------------------------------
def billing_enforced():
    v = app.config.get("BILLING_ENFORCED")
    return (not app.config.get("TESTING")) if v is None else bool(v)


def plan_prices(db=None):
    try:
        return json.loads(get_setting("plan_prices", "{}", db) or "{}")
    except ValueError:
        return {}


def vat_rate(db=None):
    v = get_setting("vat_rate", None, db)
    return BILL.DEFAULT_VAT if v is None else (to_float(v) or 0)


def inspection_prices(db=None):
    """(prix TTC paye par le client, montant reverse a l'inspecteur)."""
    return (to_int(get_setting("inspection_price", str(BILL.INSPECTION_PRICE), db)) or BILL.INSPECTION_PRICE,
            to_int(get_setting("inspection_payout", str(BILL.INSPECTION_PAYOUT), db)) or BILL.INSPECTION_PAYOUT)


def get_sub(db, user):
    """Abonnement du proprietaire ; l'essai gratuit commence au premier passage."""
    if not user or user["role"] != "proprio":
        return None
    sub = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user["id"],)).fetchone()
    if sub is None:
        now = datetime.now(timezone.utc)
        db.execute("INSERT INTO subscriptions (user_id, plan, cycle, status, trial_end, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?)", (user["id"], "essai", "mois", "essai",
                                              (now + timedelta(days=BILL.TRIAL_DAYS)).isoformat(), now_iso(), now_iso()))
        db.commit()
        sub = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user["id"],)).fetchone()
    return sub


def active_sites(db, user_id):
    return db.execute("SELECT COUNT(*) FROM projects p WHERE owner_id = ? AND (NOT EXISTS (SELECT 1 FROM steps s WHERE "
                      "s.project_id = p.id) OR EXISTS (SELECT 1 FROM steps s WHERE s.project_id = p.id AND s.status != 'paye'))",
                      (user_id,)).fetchone()[0]


def sub_view(db, user):
    """Tout ce qu'il faut pour afficher et appliquer l'abonnement."""
    sub = get_sub(db, user)
    if sub is None:
        return None
    now = datetime.now(timezone.utc)
    status = BILL.effective_status(sub, now)
    limit = BILL.sites_limit(sub)
    used = active_sites(db, user["id"])
    open_inv = db.execute("SELECT * FROM billing_invoices WHERE user_id = ? AND status = 'a_payer' ORDER BY id DESC LIMIT 1",
                          (user["id"],)).fetchone()
    days_left = None
    if status == "essai":
        days_left = max((datetime.fromisoformat(sub["trial_end"]) - now).days, 0)
    elif status in ("actif", "impaye") and sub["period_end"]:
        days_left = (datetime.fromisoformat(sub["period_end"]) - now).days
    blocked = status in BILL.BLOCKED
    return {"sub": sub, "status": status, "plan": sub["plan"], "limit": limit, "used": used, "open": open_inv,
            "days_left": days_left, "blocked": blocked,
            "can_create": not blocked and (limit is None or used < limit),
            "price": BILL.monthly_price(sub["plan"], plan_prices(db), sub["custom_price"]) if sub["plan"] in BILL.PLANS else 0}


def billing_gate(what):
    """Refuse une option payante si l'abonnement est bloque. Retourne une redirection ou None."""
    me = current_user()
    if not billing_enforced() or not me or me["role"] != "proprio":
        return None
    v = sub_view(get_db(), me)
    if v and v["blocked"]:
        flash(_("%(what)s demande un abonnement actif. Vos chantiers en cours restent accessibles.", what=what), "error")
        return redirect(url_for("subscription"))
    return None


def create_invoice(db, user, plan, cycle, start, custom=None, ttc=None, kind="abonnement", request_id=None):
    """Facture ChantierVrai. Les prix sont TTC ; la facture detaille HT et TVA."""
    ttc = BILL.period_price(plan, cycle, plan_prices(db), custom) if ttc is None else ttc
    rate = vat_rate(db)
    amount_ht, vat = BILL.from_ttc(ttc, rate)
    year = now_iso()[:4]
    seq = db.execute("SELECT COUNT(*) FROM billing_invoices WHERE number LIKE ?", (f"CV-{year}-%",)).fetchone()[0] + 1
    end = BILL.period_end(start, cycle) if kind == "abonnement" else start
    buyer = json.dumps({"name": user["name"], "email": user["email"], "company": user["company"], "phone": user["phone"]},
                       ensure_ascii=False)
    due = max(start, datetime.now(timezone.utc)).date().isoformat()
    return db.execute("INSERT INTO billing_invoices (number, user_id, plan, cycle, period_start, period_end, amount_ht, vat_rate, "
                      "vat, amount, status, due_date, buyer, kind, inspection_request_id, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (BILL.invoice_number(year, seq), user["id"], plan, cycle, start.isoformat(), end.isoformat(),
                       amount_ht, rate, vat, ttc, "a_payer", due, buyer, kind, request_id, now_iso())).lastrowid


def invoice_paid(db, inv, method, reference=None):
    """Facture payee : l'abonnement devient (ou reste) actif jusqu'a la fin de la periode facturee."""
    if inv["status"] != "a_payer":
        return False
    db.execute("UPDATE billing_invoices SET status = 'payee', paid_at = ?, method = ?, reference = COALESCE(?, reference) "
               "WHERE id = ?", (now_iso(), method, reference, inv["id"]))
    if inv["kind"] == "inspection":
        inspection_paid(db, inv)
        return True
    sub = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (inv["user_id"],)).fetchone()
    db.execute("UPDATE subscriptions SET plan = ?, cycle = ?, status = 'actif', period_start = ?, period_end = ?, "
               "cancel_at_end = 0, updated_at = ? WHERE id = ?",
               (inv["plan"], inv["cycle"], inv["period_start"], inv["period_end"], now_iso(), sub["id"]))
    notify(None, [inv["user_id"]], L("Paiement reçu, merci"),
           L("Facture %(n)s réglée : abonnement %(plan)s actif jusqu'au %(d)s.", n=inv["number"],
             plan=L(BILL.PLANS[inv["plan"]]["label"]), d=format_d(inv["period_end"])),
           url_for("billing_invoice", inv_id=inv["id"]), important=True, db=db)
    return True


def invoice_access(inv):
    me = current_user()
    return bool(me) and (me["id"] == inv["user_id"] or can("money", me))


@app.route("/compte/abonnement", methods=["GET", "POST"])
@role_required("proprio")
def subscription():
    db = get_db()
    me = current_user()
    v = sub_view(db, me)
    if request.method == "POST":
        action = request.form.get("action")
        plan, cycle = request.form.get("plan"), request.form.get("cycle", "mois")
        if action == "choose":
            if plan == "entreprise":
                notify(None, admins(db, "commerce"), L("Demande d'offre Entreprise"),
                       L("%(n)s (%(e)s) demande un devis Entreprise : %(m)s", n=me["name"], e=me["email"],
                         m=request.form.get("message", "").strip()[:300] or "-"), "/admin#abonnements", important=True, db=db)
                db.commit()
                flash(_("Demande envoyée. L'équipe commerciale vous recontacte pour le devis."), "ok")
                return redirect(url_for("subscription"))
            if plan not in ("essentiel", "pro") or cycle not in BILL.CYCLES:
                abort(400)
            if v["open"]:
                db.execute("UPDATE billing_invoices SET status = 'annulee' WHERE id = ? AND status = 'a_payer' AND tx_ref IS NULL",
                           (v["open"]["id"],))
            now = datetime.now(timezone.utc)
            sub = v["sub"]
            start = now
            if v["status"] in ("actif",) and sub["period_end"] and datetime.fromisoformat(sub["period_end"]) > now:
                start = datetime.fromisoformat(sub["period_end"])         # le changement prend effet a l'echeance
            iid = create_invoice(db, me, plan, cycle, start)
            db.commit()
            return redirect(url_for("billing_invoice", inv_id=iid))
        if action in ("cancel", "resume") and v["status"] in ("actif", "impaye"):
            db.execute("UPDATE subscriptions SET cancel_at_end = ?, updated_at = ? WHERE id = ?",
                       (int(action == "cancel"), now_iso(), v["sub"]["id"]))
            db.commit()
            flash(_("Résiliation enregistrée : l'abonnement s'arrête à l'échéance, vos données restent accessibles.")
                  if action == "cancel" else _("Résiliation annulée."), "ok")
            return redirect(url_for("subscription"))
        abort(400)
    invoices = db.execute("SELECT * FROM billing_invoices WHERE user_id = ? ORDER BY id DESC", (me["id"],)).fetchall()
    prices = plan_prices(db)
    plans = [(k, BILL.PLANS[k], BILL.monthly_price(k, prices)) for k in BILL.PAID_PLANS]
    return render_template("subscription.html", v=v, invoices=invoices, plans=plans, ANNUAL=BILL.ANNUAL_MONTHS,
                           SUB_STATUS=tr(BILL.SUB_STATUS), INV_STATUS=tr(BILL.INV_STATUS), PLANS=BILL.PLANS,
                           CYCLES=tr(BILL.CYCLES), enforced=billing_enforced())


@app.route("/compte/factures/<int:inv_id>", methods=["GET", "POST"])
@login_required
def billing_invoice(inv_id):
    db = get_db()
    inv = db.execute("SELECT * FROM billing_invoices WHERE id = ?", (inv_id,)).fetchone()
    if inv is None:
        abort(404)
    if not invoice_access(inv):
        abort(403)
    if request.method == "POST":
        if inv["user_id"] != current_user()["id"] or inv["status"] != "a_payer":
            abort(403)
        prov = PAY.get_provider()
        ref = f"CVF{inv['id']}X{secrets.token_hex(4).upper()}"
        try:
            r = prov.deposit(ref, inv["amount"], f"ChantierVrai - facture {inv['number']}",
                             public_url(url_for("billing_return", inv_id=inv_id))
                             or request.host_url.rstrip("/") + url_for("billing_return", inv_id=inv_id),
                             public_url(url_for("cinetpay_notify", secret=notify_url_secret())) or "")
        except Exception as e:
            r = {"status": "echoue", "error": str(e)[:200]}
        db.execute("UPDATE billing_invoices SET tx_ref = ?, payment_url = ? WHERE id = ?", (ref, r.get("payment_url"), inv_id))
        if r["status"] == "reussi":
            invoice_paid(db, inv, "mobile_money", r.get("provider_ref") or ref)
            db.commit()
            flash(_("Paiement confirmé. Merci !") + (_(" (simulation)") if not prov.real else ""), "ok")
        elif r.get("payment_url"):
            db.commit()
            return redirect(r["payment_url"])
        else:
            db.commit()
            flash(_("Paiement impossible : ") + (r.get("error") or "erreur inconnue"), "error")
        return redirect(url_for("billing_invoice", inv_id=inv_id))
    buyer = json.loads(inv["buyer"] or "{}")
    return render_template("billing_invoice.html", inv=inv, buyer=buyer, PLANS=BILL.PLANS, CYCLES=tr(BILL.CYCLES),
                           INV_STATUS=tr(BILL.INV_STATUS), INV_METHODS=tr(BILL.INV_METHODS),
                           seller=get_setting("billing_seller", "", db) or env("BILLING_SELLER", "ChantierVrai"),
                           bank=get_setting("billing_bank", "", db), provider=PAY.get_provider())


def sync_invoice(db, ref):
    inv = db.execute("SELECT * FROM billing_invoices WHERE tx_ref = ?", (ref,)).fetchone()
    if inv and inv["status"] == "a_payer" and PAY.get_provider().check(ref) == "reussi":
        invoice_paid(db, inv, "mobile_money", ref)
        db.commit()


@app.route("/compte/factures/<int:inv_id>/retour")
@login_required
def billing_return(inv_id):
    db = get_db()
    inv = db.execute("SELECT * FROM billing_invoices WHERE id = ? AND user_id = ?", (inv_id, current_user()["id"])).fetchone()
    if inv is None:
        abort(404)
    if inv["tx_ref"]:
        sync_invoice(db, inv["tx_ref"])
    inv = db.execute("SELECT * FROM billing_invoices WHERE id = ?", (inv_id,)).fetchone()
    flash(_("Paiement confirmé. Merci !") if inv["status"] == "payee"
          else _("Paiement en attente de confirmation par l'opérateur."), "ok")
    return redirect(url_for("billing_invoice", inv_id=inv_id))


def billing_daily(db):
    """Renouvellements, relances, passage en impaye puis suspension, fin d'essai. Retourne un resume."""
    now = datetime.now(timezone.utc)
    out = {"factures": 0, "relances": 0, "suspendus": 0, "fin_essai": 0}
    for sub in db.execute("SELECT s.*, u.name, u.email, u.company, u.phone, u.role FROM subscriptions s JOIN users u ON "
                          "u.id = s.user_id WHERE u.deleted = 0").fetchall():
        user = db.execute("SELECT * FROM users WHERE id = ?", (sub["user_id"],)).fetchone()
        open_inv = db.execute("SELECT * FROM billing_invoices WHERE user_id = ? AND status = 'a_payer' ORDER BY id DESC LIMIT 1",
                              (sub["user_id"],)).fetchone()
        # Fin d'essai : prevenir 5 jours avant, puis le jour J (une seule fois chacun)
        if sub["status"] == "essai" and sub["trial_end"]:
            left = (datetime.fromisoformat(sub["trial_end"]) - now).days
            tag = "essai-5" if 0 <= left <= 5 else "essai-fin" if left < 0 else None
            if tag and (sub["note"] or "") != tag:
                notify(None, [sub["user_id"]], L("Votre essai gratuit se termine") if tag == "essai-5" else L("Essai gratuit terminé"),
                       L("Choisissez une offre pour continuer à créer des chantiers. Vos chantiers en cours restent accessibles."),
                       "/compte/abonnement", important=True, db=db)
                db.execute("UPDATE subscriptions SET note = ? WHERE id = ?", (tag, sub["id"]))
                out["fin_essai"] += 1
            continue
        # Renouvellement : facture 7 jours avant l'echeance
        if sub["status"] in ("actif", "impaye") and sub["period_end"] and not sub["cancel_at_end"] and not open_inv:
            end = datetime.fromisoformat(sub["period_end"])
            if end - now <= timedelta(days=BILL.RENEW_NOTICE_DAYS) and sub["plan"] in BILL.PAID_PLANS \
                    and BILL.period_price(sub["plan"], sub["cycle"], plan_prices(db), sub["custom_price"]):
                iid = create_invoice(db, user, sub["plan"], sub["cycle"], end, sub["custom_price"])
                notify(None, [sub["user_id"]], L("Facture de renouvellement"),
                       L("Votre abonnement se renouvelle le %(d)s. Réglez la facture pour continuer sans interruption.",
                         d=format_d(end.isoformat())), url_for("billing_invoice", inv_id=iid), important=True, db=db)
                out["factures"] += 1
                open_inv = db.execute("SELECT * FROM billing_invoices WHERE id = ?", (iid,)).fetchone()
        # Relances : J-3, J+3, J+10 par rapport a l'echeance de la facture
        if open_inv:
            late = (now.date() - date.fromisoformat(open_inv["due_date"])).days
            due_steps = [i for i, d in enumerate(BILL.REMIND_DAYS) if late >= d]
            if due_steps and open_inv["reminders"] < len(due_steps):
                notify(None, [sub["user_id"]], L("Facture à régler"),
                       L("Facture %(n)s de %(a)s FCFA, échéance le %(d)s. Sans paiement, la création de chantiers sera suspendue %(g)s jours après l'échéance.",
                         n=open_inv["number"], a=fcfa_txt(open_inv["amount"]), d=format_d(open_inv["due_date"]),
                         g=BILL.GRACE_DAYS), url_for("billing_invoice", inv_id=open_inv["id"]), important=True, db=db)
                db.execute("UPDATE billing_invoices SET reminders = ? WHERE id = ?", (len(due_steps), open_inv["id"]))
                out["relances"] += 1
        new = BILL.next_status(sub, now, bool(open_inv))
        if new != sub["status"]:
            db.execute("UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (new, now_iso(), sub["id"]))
            if new == "suspendu":
                out["suspendus"] += 1
                notify(None, [sub["user_id"]], L("Abonnement suspendu"),
                       L("Facture impayée : la création de chantiers et les options payantes sont suspendues. Vos chantiers en cours, preuves et paiements restent accessibles."),
                       "/compte/abonnement", important=True, db=db)
                notify(None, admins(db, "money"), L("Abonnement suspendu"),
                       L("%(n)s (%(e)s) : facture impayée depuis %(g)s jours.", n=sub["name"], e=sub["email"], g=BILL.GRACE_DAYS),
                       "/admin#abonnements", db=db)
    db.commit()
    return out


@app.route("/chantiers/<int:project_id>/paiements/depot", methods=["POST"])
@login_required
def deposit(project_id):
    if not escrow_enabled():
        load_project(project_id, roles=("owner",))
        flash(_("Le séquestre est désactivé sur ChantierVrai : aucun nouveau dépôt n'est possible."), "error")
        return redirect(url_for("project", project_id=project_id, onglet="etapes"))
    p = load_project(project_id, roles=("owner",))
    amount = to_int(request.form.get("amount"))
    if amount < 100:
        flash(_('Indiquez un montant.'), "error")
        return redirect(url_for("project", project_id=project_id, onglet="etapes"))
    db = get_db()
    prov = PAY.get_provider()
    ref = tx_ref(project_id)
    cur = db.execute("INSERT INTO transactions (project_id, user_id, kind, amount, provider, ref, status, created_at, "
                     "updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (project_id, current_user()["id"], "depot", amount, prov.name, ref, "en_attente", now_iso(),
                      now_iso()))
    tid = cur.lastrowid
    db.commit()
    try:
        r = prov.deposit(ref, amount, f"Séquestre chantier {p['name']}",
                         public_url(url_for("payment_return", project_id=project_id, ref=ref))
                         or request.host_url.rstrip("/") + url_for("payment_return", project_id=project_id, ref=ref),
                         public_url(url_for("cinetpay_notify", secret=notify_url_secret())) or "")
    except Exception as e:
        r = {"status": "echoue", "error": str(e)[:200]}
    db.execute("UPDATE transactions SET status = ?, provider_ref = ?, payment_url = ?, error = ?, updated_at = ? "
               "WHERE id = ?", (r["status"], r.get("provider_ref"), r.get("payment_url"), r.get("error"), now_iso(), tid))
    db.commit()
    if r["status"] == "reussi":
        deposit_confirmed(db, p, amount, prov)
        flash(_('Dépôt de %(amount)s FCFA confirmé', amount=format(amount, ',')).replace(",", " ") + (_(' (simulation).') if not prov.real else "."), "ok")
    elif r.get("payment_url"):
        return redirect(r["payment_url"])
    else:
        flash(_('Dépôt impossible : ') + (r.get("error") or "erreur inconnue"), "error")
    return redirect(url_for("project", project_id=project_id, onglet="etapes"))


def deposit_confirmed(db, p, amount, prov):
    sim = " (simulation)" if not prov.real else ""
    log(p["id"], L('%(amount)s FCFA déposés sur le séquestre%(sim)s', amount=format(amount, ','), sim=sim).replace(",", " "), db)
    notify(p["id"], owners_of(p, db) + [p["chef_id"]], L('Fonds bloqués sur le séquestre'),
           L('%(amount)s FCFA sont bloqués pour « %(name)s ». Ils seront versés étape par étape.%(sim)s', amount=format(amount, ','), name=p['name'], sim=sim)
           .replace(",", " "), f"/chantiers/{p['id']}?onglet=etapes", important=True, db=db)
    db.commit()


@app.route("/chantiers/<int:project_id>/paiements/retour")
@login_required
def payment_return(project_id):
    p = load_project(project_id, roles=("owner",))
    ref = request.args.get("ref", "")
    sync_transaction(get_db(), ref)
    tx = get_db().execute("SELECT * FROM transactions WHERE ref = ? AND project_id = ?", (ref, p["id"])).fetchone()
    if tx:
        flash({"reussi": _('Paiement confirmé.'), "echoue": _('Paiement refusé ou annulé.')}
              .get(tx["status"], _("Paiement en attente de confirmation par l'opérateur.")),
              "error" if tx["status"] == "echoue" else "ok")
    return redirect(url_for("project", project_id=project_id, onglet="etapes"))


def sync_transaction(db, ref, transfer_status=None):
    tx = db.execute("SELECT * FROM transactions WHERE ref = ?", (ref,)).fetchone()
    if not tx or tx["status"] != "en_attente":
        return
    prov = PAY.get_provider()
    if tx["kind"] == "depot":
        status = prov.check(ref)
    else:
        status = {"VAL": "reussi", "REJ": "echoue"}.get(transfer_status or "", "en_attente")
    if status == "en_attente":
        return
    db.execute("UPDATE transactions SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), tx["id"]))
    p = db.execute("SELECT * FROM projects WHERE id = ?", (tx["project_id"],)).fetchone()
    if tx["kind"] == "depot" and status == "reussi":
        deposit_confirmed(db, p, tx["amount"], prov)
    elif tx["kind"] == "versement" and tx["order_id"]:
        o = db.execute("SELECT * FROM orders WHERE id = ?", (tx["order_id"],)).fetchone()
        if status == "echoue" and o:
            set_order(db, o["id"], status="a_payer")
            log(p["id"], L("Paiement du fournisseur rejeté par l'opérateur pour la commande %(ref)s", ref=o["ref"]), db,
                p["owner_id"])
            notify(p["id"], owners_of(p, db), L("Paiement du fournisseur rejeté"),
                   L("Commande %(ref)s : payez le fournisseur à la main puis marquez-la payée.", ref=o["ref"]),
                   f"/commandes/{o['id']}", important=True, db=db)
    elif tx["kind"] == "versement" and tx["inspection_id"]:
        if status == "echoue":
            db.execute("UPDATE inspections SET paid = 0, pay_ref = NULL WHERE id = ?", (tx["inspection_id"],))
            log(p["id"], L("Paiement de l'inspecteur rejeté par l'opérateur"), db, p["owner_id"])
    elif tx["kind"] == "versement":
        st = db.execute("SELECT * FROM steps WHERE id = ?", (tx["step_id"],)).fetchone()
        if status == "reussi":
            db.execute("UPDATE steps SET status = 'paye', paid_at = ? WHERE id = ?", (now_iso(), st["id"]))
            log(p["id"], L('Versement confirmé pour « %(name)s »', name=st['name']), db, p["owner_id"])
            emit_event(db, p["id"], "etape.payee", {"etape_id": st["id"], "etape": st["name"], "montant": st["amount"],
                                                    "mode": "sequestre", "confirme_par_operateur": True})
        else:
            db.execute("UPDATE steps SET status = 'declare' WHERE id = ? AND status = 'versement'", (st["id"],))
            log(p["id"], L("Versement rejeté par l'opérateur pour « %(name)s » : l'étape est à revalider", name=st['name']),
                db, p["owner_id"])
            notify(p["id"], owners_of(p, db), L('Versement rejeté'),
                   L("Le versement pour « %(name)s » a été rejeté. Revalidez l'étape.", name=st['name']),
                   f"/chantiers/{p['id']}?onglet=etapes", important=True, db=db)
    db.commit()


@app.route("/paiements/cinetpay/notification/<secret>", methods=["POST", "GET"])
def cinetpay_notify(secret):
    if not hmac.compare_digest(secret, notify_url_secret()):
        abort(404)
    if request.method == "GET":
        return "OK"
    f = request.form
    db = get_db()
    if f.get("cpm_trans_id", "").startswith("CVF"):
        sync_invoice(db, f["cpm_trans_id"])
    elif f.get("cpm_trans_id"):
        sync_transaction(db, f["cpm_trans_id"])
    elif f.get("client_transaction_id"):
        sync_transaction(db, f["client_transaction_id"], f.get("treatment_status"))
    return "OK"


# --------------------------------------------------------------------------
# PV de reception et documents
# --------------------------------------------------------------------------
def make_pv(db, p, st):
    """Genere le PV de reception de l'etape (page imprimable) et l'ajoute aux documents."""
    proofs = db.execute("SELECT * FROM proofs WHERE step_id = ? AND ok = 1 ORDER BY id", (st["id"],)).fetchall()
    insp = db.execute("SELECT i.*, u.name AS inspector_name FROM inspections i JOIN users u ON u.id = i.inspector_id "
                      "WHERE i.step_id = ? AND i.status = 'realisee' ORDER BY i.id DESC LIMIT 1", (st["id"],)).fetchone()
    people = {r["id"]: r for r in db.execute("SELECT id, name, phone FROM users WHERE id IN (?, ?)",
                                             (p["owner_id"], p["chef_id"] or 0))}
    html = render_template("pv.html", p=p, st=st, proofs=proofs, insp=insp, people=people, generated=now_iso())
    name = f"pv_{st['id']}_{secrets.token_hex(6)}.html"
    with open(os.path.join(DOC_DIR, name), "w", encoding="utf-8") as fh:
        fh.write(html)
    db.execute("INSERT INTO documents (project_id, user_id, step_id, category, title, filename, original_name, sha256, "
               "size, is_public, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (p["id"], p["owner_id"], st["id"], "PV", f"PV de réception – {st['name']}", name, name,
                hashlib.sha256(html.encode()).hexdigest(), len(html.encode()), p["is_public"], now_iso()))


@app.route("/chantiers/<int:project_id>/documents", methods=["POST"])
@login_required
def upload_document(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant"))
    if g.project_role in ("inspecteur", "intervenant") and not member_can("documents"):
        abort(403)
    file = request.files.get("file")
    cat = request.form.get("category", "Autre")
    if not file or not file.filename or ext_of(file.filename) not in DOC_EXT:
        flash(_('Choisissez un fichier (PDF, Word, Excel, image, DWG, ZIP).'), "error")
    else:
        raw = file.read()
        name = f"{secrets.token_hex(12)}.{ext_of(file.filename)}"
        with open(os.path.join(DOC_DIR, name), "wb") as fh:
            fh.write(raw)
        db = get_db()
        title = request.form.get("title", "").strip()[:150] or file.filename
        db.execute("INSERT INTO documents (project_id, user_id, category, title, filename, original_name, sha256, size, "
                   "is_public, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (project_id, current_user()["id"], cat if cat in DOC_CATEGORIES else "Autre", title, name,
                    file.filename[:150], hashlib.sha256(raw).hexdigest(), len(raw),
                    1 if request.form.get("is_public") and is_owner(p) else 0, now_iso()))
        log(project_id, L('Document ajouté : %(cat)s – %(title)s', cat=cat, title=title))
        db.commit()
        flash(_('Document enregistré.'), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="dossier"))


def send_document(doc):
    as_att = ext_of(doc["filename"]) not in ("pdf", "jpg", "jpeg", "png", "html", "txt")
    return send_from_directory(DOC_DIR, doc["filename"], as_attachment=as_att,
                               download_name=doc["original_name"] or doc["filename"])


@app.route("/documents/<int:doc_id>")
@login_required
def document(doc_id):
    doc = get_db().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    load_project(doc["project_id"], roles=("owner", "chef", "inspecteur", "intervenant"))
    return send_document(doc)


@app.route("/documents/<int:doc_id>/supprimer", methods=["POST"])
@login_required
def delete_document(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    load_project(doc["project_id"], roles=("owner",))
    if doc["category"] == "PV":
        flash(_('Un PV de réception ne peut pas être supprimé.'), "error")
    else:
        db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        log(doc["project_id"], L('Document supprimé : %(title)s', title=doc['title']))
        db.commit()
    return redirect(url_for("project", project_id=doc["project_id"], onglet="dossier"))


# --------------------------------------------------------------------------
# Controle des materiaux
# --------------------------------------------------------------------------
def invoice_context(project_id):
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    plans = db.execute("SELECT * FROM materials_plan WHERE project_id = ? ORDER BY step_id, material",
                       (project_id,)).fetchall()
    invoices = db.execute("SELECT i.*, u.name AS author, st.name AS step_name, "
                          "(SELECT COUNT(*) FROM invoice_lines l WHERE l.invoice_id = i.id) AS n_lines "
                          "FROM invoices i LEFT JOIN users u ON u.id = i.user_id LEFT JOIN steps st ON st.id = i.step_id "
                          "WHERE i.project_id = ? ORDER BY i.id DESC", (project_id,)).fetchall()
    lines = db.execute("SELECT l.* FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id WHERE i.project_id = ?",
                       (project_id,)).fetchall()
    table, alerts = MAT.compare(plans, lines, steps)
    return {"mat_plans": plans, "invoices": invoices, "mat_table": table, "mat_alerts": alerts}


@app.route("/chantiers/<int:project_id>/materiaux/prevu", methods=["POST"])
@login_required
def add_material_plan(project_id):
    load_project(project_id, roles=("owner",))
    f = request.form
    st = get_step(project_id, to_int(f.get("step_id")))
    material = MAT.normalize(f.get("material_other") or f.get("material"))
    db = get_db()
    db.execute("INSERT INTO materials_plan (project_id, step_id, material, unit, qty_planned, unit_price_ref) "
               "VALUES (?,?,?,?,?,?)", (project_id, st["id"], material, f.get("unit", "").strip()[:20],
                                        to_float(f.get("qty")), to_float(f.get("price"))))
    db.commit()
    return redirect(url_for("project", project_id=project_id, onglet="dossier", _anchor="materiaux"))


@app.route("/chantiers/<int:project_id>/materiaux/prevu/<int:plan_id>/supprimer", methods=["POST"])
@login_required
def delete_material_plan(project_id, plan_id):
    load_project(project_id, roles=("owner",))
    db = get_db()
    db.execute("DELETE FROM materials_plan WHERE id = ? AND project_id = ?", (plan_id, project_id))
    db.commit()
    return redirect(url_for("project", project_id=project_id, onglet="dossier", _anchor="materiaux"))


@app.route("/chantiers/<int:project_id>/factures", methods=["POST"])
@login_required
def upload_invoice(project_id):
    p = load_project(project_id, roles=("owner", "chef"))
    back_tab = "factures" if g.project_role == "chef" else "dossier"
    file = request.files.get("file")
    if not file or ext_of(file.filename) not in INVOICE_EXT:
        flash(_('Photo ou PDF de la facture requis.'), "error")
        return redirect(url_for("project", project_id=project_id, onglet=back_tab))
    raw = file.read()
    sha = hashlib.sha256(raw).hexdigest()
    db = get_db()
    if db.execute("SELECT 1 FROM invoices WHERE sha256 = ?", (sha,)).fetchone():
        flash(_('Cette facture a déjà été envoyée.'), "error")
        return redirect(url_for("project", project_id=project_id, onglet=back_tab))
    ext = ext_of(file.filename)
    if ext == "pdf":
        name, mtype = f"{secrets.token_hex(12)}.pdf", "application/pdf"
        with open(os.path.join(INV_DIR, name), "wb") as fh:
            fh.write(raw)
    else:
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            flash(_('Image illisible.'), "error")
            return redirect(url_for("project", project_id=project_id, onglet=back_tab))
        name, mtype = save_image(img, INV_DIR, 2200), "image/jpeg"
    step_id = to_int(request.form.get("step_id"), None)
    if step_id:
        get_step(project_id, step_id)
    cur = db.execute("INSERT INTO invoices (project_id, step_id, user_id, filename, media_type, sha256, supplier, number, "
                     "inv_date, total, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (project_id, step_id, current_user()["id"], name, mtype, sha,
                      request.form.get("supplier", "").strip()[:120] or None,
                      request.form.get("number", "").strip()[:60] or None, request.form.get("inv_date") or None,
                      to_float(request.form.get("total")), "lecture_ia" if VISION.ai_enabled() else "a_saisir", now_iso()))
    iid = cur.lastrowid
    check_invoice_duplicate(db, iid)
    log(project_id, L('Facture de matériaux ajoutée'))
    db.commit()
    if VISION.ai_enabled():
        run_async(read_invoice_job, iid)
        flash(_("Facture reçue. L'IA lit les lignes, revenez dans un instant."), "ok")
    else:
        flash(_('Facture reçue. Saisissez les lignes (matériau, quantité, prix).'), "ok")
    if g.project_role == "owner":
        return redirect(url_for("invoice", project_id=project_id, invoice_id=iid))
    notify(project_id, owners_of(p), L('Nouvelle facture'), L('Le chef de chantier a ajouté une facture de matériaux.'),
           url_for("invoice", project_id=project_id, invoice_id=iid))
    db.commit()
    return redirect(url_for("invoice", project_id=project_id, invoice_id=iid))


def check_invoice_duplicate(db, iid):
    inv = db.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
    if inv["number"] and inv["supplier"]:
        dup = db.execute("SELECT id FROM invoices WHERE project_id = ? AND id != ? AND number = ? AND lower(supplier) = ?",
                         (inv["project_id"], iid, inv["number"], inv["supplier"].lower())).fetchone()
        if dup:
            db.execute("UPDATE invoices SET status = 'doublon', detail = ? WHERE id = ?",
                       (f"Même numéro et fournisseur que la facture n°{dup['id']}", iid))


def read_invoice_job(iid):
    db = connect()
    try:
        inv = db.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
        with open(os.path.join(INV_DIR, inv["filename"]), "rb") as fh:
            raw = fh.read()
        r = VISION.read_invoice(raw, inv["media_type"])
        db.execute("UPDATE invoices SET supplier = COALESCE(supplier, ?), number = COALESCE(number, ?), "
                   "inv_date = COALESCE(inv_date, ?), total = COALESCE(total, ?), status = 'a_verifier' WHERE id = ?",
                   (r["supplier"] or None, r["number"] or None, r["date"] or None, r["total"] or None, iid))
        for ln in r["lines"]:
            db.execute("INSERT INTO invoice_lines (invoice_id, step_id, material, raw_label, unit, qty, unit_price) "
                       "VALUES (?,?,?,?,?,?,?)", (iid, inv["step_id"], MAT.normalize(ln["material"]), ln["material"],
                                                  ln["unit"], ln["qty"], ln["unit_price"]))
        check_invoice_duplicate(db, iid)
        db.commit()
    except Exception as e:
        db.execute("UPDATE invoices SET status = 'a_saisir', detail = ? WHERE id = ?", (f"Lecture IA : {e}"[:300], iid))
        db.commit()
    finally:
        db.close()


@app.route("/chantiers/<int:project_id>/factures/<int:invoice_id>", methods=["GET", "POST"])
@login_required
def invoice(project_id, invoice_id):
    p = load_project(project_id, roles=("owner", "chef"))
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id = ? AND project_id = ?", (invoice_id, project_id)).fetchone()
    if inv is None:
        abort(404)
    if inv["media_type"] == "commande":
        return redirect(url_for("order", oid=int(inv["filename"])))
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "line":
            label = f.get("material_other") or f.get("material")
            sid = to_int(f.get("step_id"), None) or inv["step_id"]
            db.execute("INSERT INTO invoice_lines (invoice_id, step_id, material, raw_label, unit, qty, unit_price) "
                       "VALUES (?,?,?,?,?,?,?)", (invoice_id, sid, MAT.normalize(label), label, f.get("unit", "")[:20],
                                                  to_float(f.get("qty")), to_float(f.get("unit_price"))))
            db.execute("UPDATE invoices SET status = 'a_verifier' WHERE id = ? AND status = 'a_saisir'", (invoice_id,))
        elif action == "delete_line":
            db.execute("DELETE FROM invoice_lines WHERE id = ? AND invoice_id = ?", (to_int(f.get("line_id")), invoice_id))
        elif action == "header":
            db.execute("UPDATE invoices SET supplier = ?, number = ?, inv_date = ?, total = ?, step_id = ? WHERE id = ?",
                       (f.get("supplier", "").strip()[:120] or None, f.get("number", "").strip()[:60] or None,
                        f.get("inv_date") or None, to_float(f.get("total")), to_int(f.get("step_id"), None), invoice_id))
            if inv["status"] != "doublon":
                check_invoice_duplicate(db, invoice_id)
        elif action == "approve" and g.project_role == "owner":
            db.execute("UPDATE invoices SET status = 'validee' WHERE id = ?", (invoice_id,))
            log(project_id, L('Facture n°%(invoice_id)s vérifiée par le propriétaire', invoice_id=invoice_id))
        db.commit()
        return redirect(url_for("invoice", project_id=project_id, invoice_id=invoice_id))
    lines = db.execute("SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (invoice_id,)).fetchall()
    computed = sum((ln["qty"] or 0) * (ln["unit_price"] or 0) for ln in lines)
    return render_template("invoice.html", p=p, inv=inv, lines=lines, steps=steps, computed=computed,
                           role=g.project_role)


@app.route("/factures/<int:invoice_id>/fichier")
@login_required
def invoice_file(invoice_id):
    inv = get_db().execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if inv is None:
        abort(404)
    load_project(inv["project_id"], roles=("owner", "chef"))
    return send_from_directory(INV_DIR, inv["filename"])


# --------------------------------------------------------------------------
# Satellite, drone et 3D
# --------------------------------------------------------------------------
def last_months(n=12):
    d = date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def views_context(p):
    db = get_db()
    sats = db.execute("SELECT * FROM sat_images WHERE project_id = ? ORDER BY month DESC, layer", (p["id"],)).fetchall()
    layer = request.args.get("couche", "optique")
    months = [s for s in sats if s["layer"] == layer]
    a = request.args.get("avant") or (months[1]["month"] if len(months) > 1 else None)
    b = request.args.get("apres") or (months[0]["month"] if months else None)
    sa = next((s for s in months if s["month"] == a), None)
    sb = next((s for s in months if s["month"] == b), None)
    change = None
    if sa and sb and sa["id"] != sb["id"]:
        ia, ib = Image.open(os.path.join(SAT_DIR, sa["filename"])), Image.open(os.path.join(SAT_DIR, sb["filename"]))
        change = round(VISION.change_ratio(ia, ib) * 100, 1)
    media = db.execute("SELECT * FROM media3d WHERE project_id = ? ORDER BY id DESC", (p["id"],)).fetchall()
    return {"sats": sats, "layer": layer, "sat_months": months, "cmp_a": sa, "cmp_b": sb, "change": change,
            "months": last_months(), "media3d": media}


def store_sat(db, p, month, layer, img, source):
    name = f"sat_{p['id']}_{month}_{layer}_{secrets.token_hex(4)}.png"
    img.convert("RGB").save(os.path.join(SAT_DIR, name), "PNG")
    prev = db.execute("SELECT * FROM sat_images WHERE project_id = ? AND layer = ? AND month < ? ORDER BY month DESC "
                      "LIMIT 1", (p["id"], layer, month)).fetchone()
    change = None
    if prev:
        change = round(VISION.change_ratio(Image.open(os.path.join(SAT_DIR, prev["filename"])), img) * 100, 1)
    db.execute("INSERT INTO sat_images (project_id, month, layer, filename, source, change_pct, created_at) "
               "VALUES (?,?,?,?,?,?,?) ON CONFLICT (project_id, month, layer) DO UPDATE SET filename = excluded.filename, "
               "source = excluded.source, change_pct = excluded.change_pct, created_at = excluded.created_at",
               (p["id"], month, layer, name, source, change, now_iso()))
    return change


@app.route("/chantiers/<int:project_id>/satellite", methods=["POST"])
@login_required
def satellite_add(project_id):
    p = load_project(project_id, roles=("owner",))
    month = request.form.get("month", "")
    layer = request.form.get("layer", "optique")
    if layer not in SAT.LAYERS or len(month) != 7:
        abort(400)
    db = get_db()
    file = request.files.get("file")
    try:
        if file and file.filename:
            img = Image.open(io.BytesIO(file.read()))
            img.load()
            source = "manuel"
        elif SAT.configured() and layer != "thr":
            img = Image.open(io.BytesIO(SAT.fetch(p["lat"], p["lng"], month, layer)))
            img.load()
            source = "copernicus"
        else:
            flash(_("Ajoutez une image, ou configurez l'accès Copernicus pour le téléchargement automatique."), "error")
            return redirect(url_for("project", project_id=project_id, onglet="vues"))
    except Exception as e:
        flash(_('Image satellite impossible à obtenir : %(e)s', e=e), "error")
        return redirect(url_for("project", project_id=project_id, onglet="vues"))
    change = store_sat(db, p, month, layer, img, source)
    log(project_id, L('Image satellite %(v)s de %(month)s ajoutée', v=L(layer), month=month)
        + (L(' (%(change)s %% de changement)', change=change) if change is not None else ""))
    db.commit()
    flash(_('Image satellite enregistrée.'), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="vues", couche=layer))


@app.route("/satellite/<int:sat_id>")
@login_required
def satellite_image(sat_id):
    s = get_db().execute("SELECT * FROM sat_images WHERE id = ?", (sat_id,)).fetchone()
    if s is None:
        abort(404)
    load_project(s["project_id"], roles=("owner", "chef", "inspecteur", "intervenant"))
    return send_from_directory(SAT_DIR, s["filename"])


@app.route("/satellite/changements/<int:a>/<int:b>")
@login_required
def satellite_change(a, b):
    db = get_db()
    sa = db.execute("SELECT * FROM sat_images WHERE id = ?", (a,)).fetchone()
    sb = db.execute("SELECT * FROM sat_images WHERE id = ?", (b,)).fetchone()
    if not sa or not sb or sa["project_id"] != sb["project_id"]:
        abort(404)
    load_project(sa["project_id"])
    img = VISION.change_map(Image.open(os.path.join(SAT_DIR, sa["filename"])),
                            Image.open(os.path.join(SAT_DIR, sb["filename"])))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), mimetype="image/jpeg")


def monthly_satellite(db):
    """Telecharge automatiquement l'image du mois precedent pour chaque chantier (si configure)."""
    if not SAT.configured():
        return 0
    month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    n = 0
    for p in db.execute("SELECT * FROM projects").fetchall():
        for layer in [k for k in SAT.LAYERS if k != "thr"]:
            if db.execute("SELECT 1 FROM sat_images WHERE project_id = ? AND month = ? AND layer = ?",
                          (p["id"], month, layer)).fetchone():
                continue
            try:
                img = Image.open(io.BytesIO(SAT.fetch(p["lat"], p["lng"], month, layer)))
                img.load()
                store_sat(db, p, month, layer, img, "copernicus")
                n += 1
            except Exception as e:
                log(p["id"], L('Image satellite %(month)s indisponible : %(v)s', month=month, v=str(e)[:120]), db, p["owner_id"])
        db.commit()
    return n


@app.route("/chantiers/<int:project_id>/drone", methods=["POST"])
@login_required
def upload_media3d(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur"))
    files = request.files.getlist("files")
    kind = request.form.get("kind", "drone")
    if kind not in ("drone", "modele3d", "orthophoto"):
        abort(400)
    db = get_db()
    added, refused = 0, []
    for file in files:
        if not file or not file.filename:
            continue
        ext = ext_of(file.filename)
        lat = lng = dist = taken = None
        if kind == "modele3d":
            if ext not in M3D_EXT:
                refused.append(_('%(filename)s : format 3D accepté GLB ou GLTF', filename=file.filename))
                continue
            name = f"{secrets.token_hex(12)}.{ext}"
            file.save(os.path.join(M3D_DIR, name))
        else:
            if ext not in IMG_EXT:
                refused.append(_('%(filename)s : image attendue', filename=file.filename))
                continue
            try:
                img = Image.open(io.BytesIO(file.read()))
                img.load()
            except Exception:
                refused.append(_('%(filename)s : image illisible', filename=file.filename))
                continue
            lat, lng, t = read_exif(img)
            taken = t.isoformat() if t else None
            if lat is not None:
                dist, limit, _parcel = site_distance(p, lat, lng)
                if dist > limit + DRONE_EXTRA_METERS:
                    refused.append(_('%(filename)s : prise à %(dist)s m du terrain', filename=file.filename, dist=dist))
                    continue
            name = save_image(img, M3D_DIR, 4000 if kind == "orthophoto" else 2400)
        db.execute("INSERT INTO media3d (project_id, user_id, kind, filename, original_name, lat, lng, distance, taken, "
                   "note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (project_id, current_user()["id"], kind, name, file.filename[:150], lat, lng, dist, taken,
                    request.form.get("note", "").strip()[:300], now_iso()))
        added += 1
    if added:
        label = {"drone": L("vue(s) de drone"), "modele3d": L("modèle(s) 3D"), "orthophoto": L("orthophoto(s)")}[kind]
        log(project_id, L('%(added)s %(label)s ajouté(s)', added=added, label=label))
        if g.project_role != "owner":
            notify(project_id, owners_of(p), L('Nouvelles vues du chantier'), L('%(added)s %(label)s ajouté(s).', added=added, label=label),
                   url_for("project", project_id=project_id, onglet="vues"))
    db.commit()
    for r in refused:
        flash(r, "error")
    if added:
        flash(_('%(added)s fichier(s) ajouté(s).', added=added), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="vues"))


@app.route("/drone3d/<int:media_id>")
@login_required
def media3d_file(media_id):
    m = get_db().execute("SELECT * FROM media3d WHERE id = ?", (media_id,)).fetchone()
    if m is None:
        abort(404)
    load_project(m["project_id"], roles=("owner", "chef", "inspecteur", "intervenant"))
    mt = "model/gltf-binary" if m["filename"].endswith(".glb") else None
    return send_from_directory(M3D_DIR, m["filename"], mimetype=mt)


# --------------------------------------------------------------------------
# Inspections independantes
# --------------------------------------------------------------------------
@app.route("/chantiers/<int:project_id>/inspections", methods=["POST"])
@login_required
def book_inspection(project_id):
    """Inspection independante vendue par ChantierVrai : prix fixe paye a ChantierVrai, inspecteur attribue par
    l'equipe et paye par ChantierVrai. Le proprietaire ne choisit ni ne paie l'inspecteur."""
    p = load_project(project_id, roles=("owner",))
    f = request.form
    db = get_db()
    step_id = to_int(f.get("step_id"), None)
    st = get_step(project_id, step_id) if step_id else None
    price, payout = inspection_prices(db)
    me = current_user()
    rid = db.execute("INSERT INTO inspection_requests (project_id, step_id, requested_by, wanted_date, message, price, payout, "
                     "status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (project_id, step_id, me["id"], f.get("wanted_date") or None, f.get("message", "").strip()[:500],
                      price, payout, "a_payer", now_iso())).lastrowid
    iid = create_invoice(db, me, "inspection", "unique", datetime.now(timezone.utc), ttc=price, kind="inspection",
                         request_id=rid)
    db.execute("UPDATE inspection_requests SET invoice_id = ? WHERE id = ?", (iid, rid))
    log(project_id, L("Inspection indépendante commandée") + (L(' pour « %(name)s »', name=st['name']) if st else ""))
    db.commit()
    flash(_("Réglez la facture : un inspecteur indépendant est attribué dès le paiement."), "ok")
    return redirect(url_for("billing_invoice", inv_id=iid))


def inspection_paid(db, inv):
    """Facture d'inspection payee : la demande part a l'equipe pour attribution."""
    r = db.execute("SELECT * FROM inspection_requests WHERE id = ?", (inv["inspection_request_id"],)).fetchone()
    if r is None or r["status"] != "a_payer":
        return
    db.execute("UPDATE inspection_requests SET status = 'a_attribuer' WHERE id = ?", (r["id"],))
    p = db.execute("SELECT * FROM projects WHERE id = ?", (r["project_id"],)).fetchone()
    notify(p["id"], [r["requested_by"]], L("Inspection payée"),
           L("Un inspecteur indépendant vérifié va être attribué par ChantierVrai. Vous serez prévenu de son nom et de sa date de passage."),
           url_for("project", project_id=p["id"], onglet="dossier", _anchor="inspections"), important=True, db=db)
    notify(None, admins(db, "inspections"), L("Inspection à attribuer"),
           L("%(p)s (%(a)s) : choisissez un inspecteur vérifié.", p=p["name"], a=p["address"] or p["commune"] or "-"),
           "/admin#inspections", db=db)


@app.route("/inspections/demandes/<int:rid>/annuler", methods=["POST"])
@login_required
def cancel_inspection_request(rid):
    db = get_db()
    r = db.execute("SELECT * FROM inspection_requests WHERE id = ?", (rid,)).fetchone()
    if r is None:
        abort(404)
    load_project(r["project_id"], roles=("owner",))
    if r["status"] != "a_payer":
        flash(_("L'inspection est payée : pour l'annuler, écrivez au support."), "error")
    else:
        db.execute("UPDATE inspection_requests SET status = 'annulee' WHERE id = ?", (rid,))
        db.execute("UPDATE billing_invoices SET status = 'annulee' WHERE id = ? AND status = 'a_payer'", (r["invoice_id"],))
        db.commit()
    return redirect(url_for("project", project_id=r["project_id"], onglet="dossier", _anchor="inspections"))


@app.route("/admin/inspections", methods=["POST"])
@admin_required
def admin_inspections():
    """Attribution d'un inspecteur verifie a une inspection payee ; reversement a l'inspecteur (finance)."""
    db = get_db()
    me = current_user()
    f = request.form
    action = f.get("action")
    if action == "assign":
        if not can("inspections", me):
            abort(403)
        r = db.execute("SELECT * FROM inspection_requests WHERE id = ? AND status = 'a_attribuer'", (to_int(f.get("id")),)).fetchone()
        insp = db.execute("SELECT * FROM users WHERE id = ? AND role = 'inspecteur' AND verified = 1 AND blocked = 0 AND deleted = 0",
                          (to_int(f.get("inspector_id")),)).fetchone()
        if r is None or insp is None:
            abort(404)
        p = db.execute("SELECT * FROM projects WHERE id = ?", (r["project_id"],)).fetchone()
        st = db.execute("SELECT * FROM steps WHERE id = ?", (r["step_id"],)).fetchone() if r["step_id"] else None
        iid = db.execute("INSERT INTO inspections (project_id, step_id, inspector_id, requested_by, wanted_date, message, fee, "
                         "status, created_at, sold, request_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (p["id"], r["step_id"], insp["id"], r["requested_by"], r["wanted_date"], r["message"], r["payout"],
                          "demandee", now_iso(), 1, r["id"])).lastrowid
        db.execute("UPDATE inspection_requests SET status = 'attribuee', inspection_id = ?, assigned_by = ?, assigned_at = ? "
                   "WHERE id = ?", (iid, me["id"], now_iso(), r["id"]))
        log(p["id"], L("Inspecteur indépendant attribué par ChantierVrai : %(name)s", name=insp["name"]), db, me["id"])
        notify(p["id"], [insp["id"]], L("Nouvelle demande d'inspection"),
               L("Inspection attribuée par ChantierVrai : %(p)s%(st)s. Rémunération : %(v)s FCFA, versée par ChantierVrai après le rapport.",
                 p=p["name"], st=L(', étape « %(name)s »', name=st['name']) if st else "", v=fcfa_txt(r["payout"])),
               "/", important=True, db=db)
        notify(p["id"], [r["requested_by"]], L("Inspecteur attribué"),
               L("%(name)s, inspecteur vérifié et payé par ChantierVrai, va contrôler votre chantier.", name=insp["name"]),
               url_for("project", project_id=p["id"], onglet="dossier", _anchor="inspections"), important=True, db=db)
        staff_log(db, me, "inspection_assign", iid)
    elif action == "payout":
        if not can("money", me):
            abort(403)
        i = db.execute("SELECT * FROM inspections WHERE id = ? AND sold = 1 AND payout_status = 'a_verser'",
                       (to_int(f.get("id")),)).fetchone()
        ref = f.get("reference", "").strip()[:80]
        if i is None:
            abort(404)
        if not ref:
            flash(_("Indiquez la référence du versement à l'inspecteur."), "error")
            return redirect(url_for("admin", _anchor="inspections"))
        db.execute("UPDATE inspections SET paid = 1, pay_ref = ?, payout_status = 'verse', payout_at = ? WHERE id = ?",
                   (ref, now_iso(), i["id"]))
        notify(i["project_id"], [i["inspector_id"]], L("Rémunération versée"),
               L("ChantierVrai vous a versé %(v)s FCFA pour votre inspection (réf. %(r)s).", v=fcfa_txt(i["fee"]), r=ref),
               "/", db=db)
        staff_log(db, me, "inspection_payout", i["id"])
    else:
        abort(400)
    db.commit()
    flash(_("Action effectuée."), "ok")
    return redirect(url_for("admin", _anchor="inspections"))


def get_inspection(iid):
    i = get_db().execute("SELECT * FROM inspections WHERE id = ?", (iid,)).fetchone()
    if i is None:
        abort(404)
    return i


@app.route("/inspections/<int:iid>/reponse", methods=["POST"])
@role_required("inspecteur")
def answer_inspection(iid):
    i = get_inspection(iid)
    if i["inspector_id"] != current_user()["id"] or i["status"] != "demandee":
        abort(403)
    accept = request.form.get("decision") == "accepter"
    db = get_db()
    db.execute("UPDATE inspections SET status = ? WHERE id = ?", ("acceptee" if accept else "refusee", iid))
    if not accept and i["sold"] and i["request_id"]:
        db.execute("UPDATE inspection_requests SET status = 'a_attribuer', inspection_id = NULL WHERE id = ?", (i["request_id"],))
        notify(None, admins(db, "inspections"), L("Inspection à attribuer"),
               L("%(name)s a refusé l'inspection : choisissez un autre inspecteur.", name=current_user()["name"]),
               "/admin#inspections", db=db)
        db.commit()
        return redirect(url_for("home"))
    log(i["project_id"], (L('Inspection acceptée par %(name)s', name=current_user()['name']) if accept else L('Inspection refusée par %(name)s', name=current_user()['name'])))
    notify(i["project_id"], [i["requested_by"]], L('Inspection ') + (L('acceptée') if accept else L('refusée')),
           (L("%(name)s a accepté votre demande d'inspection.", name=current_user()['name']) if accept else L("%(name)s a refusé votre demande d'inspection.", name=current_user()['name'])),
           url_for("project", project_id=i["project_id"], onglet="dossier"), important=True)
    db.commit()
    if accept:
        return redirect(url_for("project", project_id=i["project_id"]))
    return redirect(url_for("home"))


@app.route("/inspections/<int:iid>/annuler", methods=["POST"])
@login_required
def cancel_inspection(iid):
    i = get_inspection(iid)
    load_project(i["project_id"], roles=("owner",))
    if i["sold"]:
        flash(_("L'inspection est payée à ChantierVrai : pour l'annuler, écrivez au support."), "error")
    elif i["status"] in ("demandee", "acceptee"):
        db = get_db()
        db.execute("UPDATE inspections SET status = 'annulee' WHERE id = ?", (iid,))
        notify(i["project_id"], [i["inspector_id"]], L('Inspection annulée'), L("Le propriétaire a annulé l'inspection."), "/")
        db.commit()
    return redirect(url_for("project", project_id=i["project_id"], onglet="dossier"))


@app.route("/inspections/<int:iid>/preuves", methods=["POST"])
@role_required("inspecteur")
def inspection_proof(iid):
    i = get_inspection(iid)
    p = load_project(i["project_id"], roles=("inspecteur",))
    if i["inspector_id"] != current_user()["id"] or i["status"] != "acceptee":
        abort(403)
    db = get_db()
    st = db.execute("SELECT * FROM steps WHERE id = ?", (i["step_id"],)).fetchone() if i["step_id"] else None
    st = st or project_stats(p["id"])["current"] or db.execute(
        "SELECT * FROM steps WHERE project_id = ? ORDER BY position DESC LIMIT 1", (p["id"],)).fetchone()
    ok, reasons = process_proof(p, st, current_user(), source="inspecteur", inspection_id=iid)
    if ok is None:
        flash(reasons, "error")
    else:
        flash(_("Photo d'inspection vérifiée.") if ok else _('Photo refusée : ') + "; ".join(map(I18N.render, reasons)), "ok" if ok else "error")
    return redirect(url_for("project", project_id=p["id"]))


@app.route("/inspections/<int:iid>/rapport", methods=["POST"])
@role_required("inspecteur")
def inspection_report(iid):
    i = get_inspection(iid)
    load_project(i["project_id"], roles=("inspecteur",))
    if i["inspector_id"] != current_user()["id"] or i["status"] != "acceptee":
        abort(403)
    verdict = request.form.get("verdict")
    text = request.form.get("report", "").strip()[:5000]
    db = get_db()
    n_ok = db.execute("SELECT COUNT(*) FROM proofs WHERE inspection_id = ? AND ok = 1", (iid,)).fetchone()[0]
    if verdict not in VERDICTS or len(text) < 20:
        flash(_('Choisissez un avis et rédigez un rapport (20 caractères minimum).'), "error")
    elif n_ok == 0:
        flash(_('Envoyez au moins une photo vérifiée prise sur le terrain avant le rapport.'), "error")
    else:
        db.execute("UPDATE inspections SET status = 'realisee', verdict = ?, report = ?, done_at = ?, "
                   "payout_status = CASE WHEN sold = 1 THEN 'a_verser' ELSE payout_status END WHERE id = ?",
                   (verdict, text, now_iso(), iid))
        if i["sold"]:
            notify(None, admins(db, "money"), L("Inspecteur à payer"),
                   L("%(name)s a rendu son rapport : %(v)s FCFA à lui verser.", name=current_user()["name"], v=fcfa_txt(i["fee"])),
                   "/admin#inspections", db=db)
        log(i["project_id"], L("Rapport d'inspection : %(v)s", v=L(VERDICTS[verdict])))
        notify(i["project_id"], [i["requested_by"]], L("Rapport d'inspection : %(v)s", v=L(VERDICTS[verdict])), text[:300],
               url_for("project", project_id=i["project_id"], onglet="dossier"), important=True)
        db.commit()
        flash(_('Rapport envoyé au propriétaire.'), "ok")
    return redirect(url_for("project", project_id=i["project_id"]))


@app.route("/inspections/<int:iid>/payer", methods=["POST"])
@login_required
def pay_inspection(iid):
    i = get_inspection(iid)
    p = load_project(i["project_id"], roles=("owner",))
    db = get_db()
    back = redirect(url_for("project", project_id=p["id"], onglet="dossier", _anchor="inspections"))
    if i["status"] != "realisee" or i["paid"] or not i["fee"] or i["sold"]:
        flash(_("Cette inspection n'est pas à payer."), "error")
        return back
    insp = db.execute("SELECT * FROM users WHERE id = ?", (i["inspector_id"],)).fetchone()
    if p["pay_mode"] == "suivi":
        return redirect(url_for("pay_order", kind="inspection", ref_id=iid))
    if p["pay_mode"] == "sequestre" and request.form.get("via") != "manuel":
        if escrow(p["id"])["balance"] < i["fee"]:
            flash(_("Solde du séquestre insuffisant pour payer l'inspecteur."), "error")
            return back
        prov = PAY.get_provider()
        ref = tx_ref(p["id"])
        cur = db.execute("INSERT INTO transactions (project_id, user_id, kind, amount, provider, ref, status, created_at, "
                         "updated_at, inspection_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (p["id"], current_user()["id"], "versement", i["fee"], prov.name, ref, "en_attente",
                          now_iso(), now_iso(), iid))
        db.commit()
        try:
            r = prov.payout(ref, i["fee"], insp["phone"], insp["name"],
                            public_url(url_for("cinetpay_notify", secret=notify_url_secret())) or "")
        except Exception as e:
            r = {"status": "echoue", "error": str(e)[:200]}
        db.execute("UPDATE transactions SET status = ?, provider_ref = ?, error = ?, updated_at = ? WHERE id = ?",
                   (r["status"], r.get("provider_ref"), r.get("error"), now_iso(), cur.lastrowid))
        if r["status"] == "echoue":
            db.commit()
            flash(_("Paiement de l'inspecteur échoué : ") + (r.get("error") or "erreur inconnue"), "error")
            return back
        ref_txt = r.get("provider_ref") or ref
    else:
        ref_txt = request.form.get("pay_ref", "").strip()[:80] or "manuel"
    db.execute("UPDATE inspections SET paid = 1, pay_ref = ? WHERE id = ?", (ref_txt, iid))
    log(p["id"], L('Inspection payée à %(name)s (%(fee)s FCFA)', name=insp['name'], fee=format(i['fee'], ',')).replace(",", " "))
    notify(p["id"], [insp["id"]], L('Inspection payée'), L('%(fee)s FCFA pour « %(name)s ».', fee=format(i['fee'], ','), name=p['name']).replace(",", " "),
           "/", important=True)
    db.commit()
    flash(_('Inspecteur payé.'), "ok")
    return back


# --------------------------------------------------------------------------
# Litiges et mediation
# --------------------------------------------------------------------------
def dispute_parties(db, d):
    p = db.execute("SELECT * FROM projects WHERE id = ?", (d["project_id"],)).fetchone()
    return p, [u for u in owners_of(p, db) + [p["chef_id"]] if u]


def admins(db, perm=None):
    """Membres de l'equipe a prevenir ; perm limite aux roles concernes (verify, disputes, imagery...)."""
    rows = db.execute("SELECT * FROM users WHERE is_admin = 1 AND blocked = 0 AND deleted = 0").fetchall()
    return [r["id"] for r in rows if perm is None or perm in STAFF_PERMS[staff_role(r)]]


@app.route("/chantiers/<int:project_id>/litiges", methods=["POST"])
@login_required
def open_dispute(project_id):
    p = load_project(project_id, roles=("owner", "chef"))
    db = get_db()
    step_id = to_int(request.form.get("step_id"), None)
    if step_id:
        get_step(project_id, step_id)
    subject = request.form.get("subject", "").strip()[:150]
    text = request.form.get("text", "").strip()[:3000]
    if len(subject) < 5 or len(text) < 20:
        flash(_("Indiquez l'objet du litige et expliquez la situation (20 caractères minimum)."), "error")
        return redirect(request.referrer or url_for("project", project_id=project_id))
    if db.execute("SELECT 1 FROM disputes WHERE project_id = ? AND status IN ('ouvert', 'en_appel') AND COALESCE(step_id, 0) = ?",
                  (project_id, step_id or 0)).fetchone():
        flash(_('Un litige est déjà ouvert sur cette étape.'), "error")
        return redirect(request.referrer or url_for("project", project_id=project_id))
    cur = db.execute("INSERT INTO disputes (project_id, step_id, opened_by, subject, created_at, stage, respond_by) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (project_id, step_id, current_user()["id"], subject, now_iso(), "echanges",
                      (datetime.now(timezone.utc) + timedelta(days=DISPUTE_RESPOND_DAYS)).isoformat()))
    did = cur.lastrowid
    db.execute("INSERT INTO dispute_messages (dispute_id, user_id, text, created_at) VALUES (?,?,?,?)",
               (did, current_user()["id"], text, now_iso()))
    log(project_id, L('Litige ouvert : %(subject)s', subject=subject))
    _p, parties = dispute_parties(db, {"project_id": project_id})
    notify(project_id, [u for u in parties if u != current_user()["id"]] + admins(db, "disputes"), L('Litige ouvert'),
           f"« {p['name']} » : {subject}", url_for("dispute", did=did), important=True)
    db.commit()
    flash(_("Litige ouvert. L'autre partie et l'équipe de médiation sont prévenues."), "ok")
    return redirect(url_for("dispute", did=did))


@app.route("/litiges/<int:did>", methods=["GET", "POST"])
@login_required
def dispute(did):
    db = get_db()
    d = db.execute("SELECT * FROM disputes WHERE id = ?", (did,)).fetchone()
    if d is None:
        abort(404)
    me = current_user()
    p = load_project(d["project_id"], roles=("owner", "chef", "admin")) if not can("platform", me) or d["status"] != "en_appel" \
        else db.execute("SELECT * FROM projects WHERE id = ?", (d["project_id"],)).fetchone()
    role = g.get("project_role") or "admin"
    _p, parties = dispute_parties(db, d)
    if request.method == "POST":
        action = request.form.get("action")
        text = request.form.get("text", "").strip()[:3000]
        back = redirect(url_for("dispute", did=did))
        if action == "appeal":
            # Recours : une seule fois, par une partie, dans les 7 jours suivant une decision de la mediation
            if d["status"] != "resolu" or me["id"] not in parties or d["outcome"] in (None, "amiable") \
                    or not d["appeal_until"] or datetime.fromisoformat(d["appeal_until"]) <= datetime.now(timezone.utc):
                abort(400)
            if len(text) < 20:
                flash(_("Expliquez votre recours (20 caractères minimum) : élément nouveau, preuve ignorée…"), "error")
                return back
            db.execute("UPDATE disputes SET status = 'en_appel', stage = 'en_appel', appeal_text = ?, appealed_by = ?, "
                       "appealed_at = ? WHERE id = ?", (text, me["id"], now_iso(), did))
            log(p["id"], L("Recours contre la décision du litige « %(s)s »", s=d["subject"]), db, me["id"])
            notify(p["id"], [u for u in parties if u != me["id"]] + admins(db, "platform"), L("Recours sur un litige"),
                   text[:300], url_for("dispute", did=did), important=True, db=db)
            db.commit()
            flash(_("Recours enregistré. Le fondateur de ChantierVrai rend la décision finale."), "ok")
            return back
        if action == "final":
            if d["status"] != "en_appel" or not can("platform", me) or len(text) < 10:
                abort(400 if can("platform", me) else 403)
            db.execute("UPDATE disputes SET status = 'clos', stage = 'clos', final_decision = ?, final_by = ?, final_at = ? "
                       "WHERE id = ?", (text, me["id"], now_iso(), did))
            log(p["id"], L("Décision finale sur le litige : %(v)s", v=text[:150]), db, me["id"])
            notify(p["id"], parties, L("Décision finale du litige"), text[:300], url_for("dispute", did=did),
                   important=True, db=db)
            staff_log(db, me, "dispute_final", did)
            db.commit()
            return back
        if d["status"] != "ouvert":
            abort(400)
        if action == "message" and text:
            db.execute("INSERT INTO dispute_messages (dispute_id, user_id, text, created_at) VALUES (?,?,?,?)",
                       (did, me["id"], text, now_iso()))
            notify(p["id"], [u for u in parties + admins(db, "disputes") if u != me["id"]], L('Nouveau message dans un litige'),
                   text[:200], url_for("dispute", did=did), important=role == "admin")
        elif action == "mediation" and me["id"] in parties and d["stage"] == "echanges":
            decide = (datetime.now(timezone.utc) + timedelta(days=DISPUTE_DECIDE_DAYS)).isoformat()
            db.execute("UPDATE disputes SET stage = 'mediation', decide_by = ? WHERE id = ?", (decide, did))
            notify(p["id"], [u for u in parties if u != me["id"]] + admins(db, "disputes"), L("Litige en médiation"),
                   L("« %(s)s » : %(who)s demande la médiation. Décision avant le %(d)s.", s=d["subject"], who=me["name"],
                     d=format_d(decide)), url_for("dispute", did=did), important=True, db=db)
        elif action == "resolve" and role == "admin" and len(text) >= 10:
            outcome = request.form.get("outcome") if request.form.get("outcome") in DISPUTE_OUTCOMES else "recommandation"
            amount = to_int(request.form.get("amount"), None)
            until = (datetime.now(timezone.utc) + timedelta(days=DISPUTE_APPEAL_DAYS)).isoformat()
            db.execute("UPDATE disputes SET status = 'resolu', stage = 'resolu', resolution = ?, outcome = ?, amount = ?, "
                       "resolved_by = ?, resolved_at = ?, appeal_until = ? WHERE id = ?",
                       (text, outcome, amount, me["id"], now_iso(), until, did))
            log(p["id"], L('Litige tranché par la médiation') + f" : {text[:150]}", db, me["id"])
            notify(p["id"], [u for u in parties if u != me["id"]], L('Litige résolu'),
                   L("Décision de la médiation (%(o)s). Recours possible jusqu'au %(d)s.", o=L(DISPUTE_OUTCOMES[outcome]),
                     d=format_d(until)) + " " + text[:250], url_for("dispute", did=did), important=True)
            staff_log(db, me, f"dispute_decision:{outcome}", did)
        elif action == "resolve" and me["id"] == d["opened_by"] and len(text) >= 10:
            db.execute("UPDATE disputes SET status = 'clos', stage = 'clos', outcome = 'amiable', resolution = ?, "
                       "resolved_by = ?, resolved_at = ? WHERE id = ?", (text, me["id"], now_iso(), did))
            log(p["id"], L("Litige clos à l'amiable") + f" : {text[:150]}", db, me["id"])
            notify(p["id"], [u for u in parties if u != me["id"]], L('Litige résolu'), text[:300],
                   url_for("dispute", did=did), important=True)
        else:
            flash(_('Message vide, ou résolution trop courte (10 caractères minimum).'), "error")
        db.commit()
        return back
    msgs = db.execute("SELECT m.*, u.name, u.is_admin FROM dispute_messages m JOIN users u ON u.id = m.user_id "
                      "WHERE dispute_id = ? ORDER BY m.id", (did,)).fetchall()
    st = db.execute("SELECT * FROM steps WHERE id = ?", (d["step_id"],)).fetchone() if d["step_id"] else None
    proofs = [pr for pr in proofs_of(p["id"]) if not st or pr["step_id"] == st["id"]][:30]
    insp = db.execute("SELECT i.*, u.name AS inspector_name FROM inspections i JOIN users u ON u.id = i.inspector_id "
                      "WHERE i.project_id = ? AND i.status = 'realisee' ORDER BY i.id DESC", (p["id"],)).fetchall()
    history = db.execute("SELECT activity.*, users.name AS author FROM activity LEFT JOIN users ON users.id = activity.user_id "
                         "WHERE project_id = ? ORDER BY activity.id DESC LIMIT 40", (p["id"],)).fetchall()
    pay_recs = db.execute("SELECT r.*, u.name AS payer_name FROM payment_records r LEFT JOIN users u ON u.id = r.payer_id "
                          "WHERE r.project_id = ? AND (? IS NULL OR (r.kind = 'etape' AND r.ref_id = ?)) ORDER BY r.id",
                          (p["id"], d["step_id"], d["step_id"])).fetchall()
    pvs = db.execute("SELECT * FROM documents WHERE project_id = ? AND category = 'PV' AND (? IS NULL OR step_id = ?) "
                     "ORDER BY id", (p["id"], d["step_id"], d["step_id"])).fetchall()
    return render_template("dispute.html", d=d, p=p, st=st, msgs=msgs, proofs=proofs, insp=insp, history=history,
                           role=role, can_resolve=role == "admin" or me["id"] == d["opened_by"], is_party=me["id"] in parties,
                           pay_recs=pay_recs, pvs=pvs, OUTCOMES=tr(DISPUTE_OUTCOMES), STAGES=tr(DISPUTE_STAGES),
                           PAY_METHODS=tr(PAY_METHODS), PAY_REC_STATUS=tr(PAY_REC_STATUS),
                           appeal_open=d["status"] == "resolu" and d["appeal_until"] and
                           datetime.fromisoformat(d["appeal_until"]) > datetime.now(timezone.utc) and d["outcome"] != "amiable",
                           RULES=dict(respond=DISPUTE_RESPOND_DAYS, decide=DISPUTE_DECIDE_DAYS, appeal=DISPUTE_APPEAL_DAYS))


# --------------------------------------------------------------------------
# Administration
# --------------------------------------------------------------------------
MONTHS_SHORT = {"fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
                "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}


def compact(n):
    """1 250 000 -> « 1,3 M » ; 45 000 -> « 45 k » (axes et étiquettes des graphiques)."""
    n = int(n or 0)
    sep = "," if I18N.current_lang() == "fr" else "."
    def half_up(x, digits=0):
        q = Decimal(1).scaleb(-digits)
        return Decimal(x).quantize(q, rounding=ROUND_HALF_UP)
    if abs(n) >= 1_000_000:
        v = half_up(Decimal(n) / 1_000_000, 1)
        txt = str(v.to_integral_value()) if v == v.to_integral_value() else str(v).replace(".", sep)
        return txt + " M"
    if abs(n) >= 10_000:
        return f"{half_up(Decimal(n) / 1000)} k"
    return fcfa_txt(n)


@app.route("/admin/pilotage")
@admin_required(perm="money")
def pilotage():
    """Tableau de pilotage de l'activité (fondateur et équipe finance)."""
    db = get_db()
    period = request.args.get("periode", "30")
    days = KPI.PERIODS.get(period, 30)
    tiles = KPI.tiles(db, days, plan_prices(db))
    tr_ = KPI.trends(db)
    names = MONTHS_SHORT.get(I18N.current_lang(), MONTHS_SHORT["fr"])
    labels = [names[int(m[5:7]) - 1] for m in tr_["months"]]
    full = [names[int(m[5:7]) - 1] + " " + m[:4] for m in tr_["months"]]
    charts = [
        {"id": "ca", "title": _("Chiffre d'affaires encaissé par mois"), "unit": "FCFA HT", "kind": "bars", "money": True,
         "g": KPI.bars(tr_["revenue"], labels), "values": tr_["revenue"],
         "detail": [[_("Abonnements et inspections"), tr_["rev_inv"]], [_("Commissions sur les matériaux"), tr_["rev_com"]]]},
        {"id": "suivi", "title": _("Argent suivi sur les chantiers par mois"), "unit": "FCFA", "kind": "bars", "money": True,
         "g": KPI.bars(tr_["money"], labels), "values": tr_["money"], "detail": []},
        {"id": "clients", "title": _("Nouveaux clients par mois"), "unit": "", "kind": "bars", "money": False,
         "g": KPI.bars(tr_["clients"], labels), "values": tr_["clients"], "detail": []},
        {"id": "actifs", "title": _("Chantiers actifs par mois"), "unit": "", "kind": "line", "money": False,
         "g": KPI.line(tr_["active"], labels), "values": tr_["active"], "detail": []},
    ]
    return render_template("pilotage.html", tiles=tiles, charts=charts, full=full, period=period, days=days,
                           funnel=KPI.funnel(db), funnel_period=KPI.funnel(db, days), watch=KPI.watch(db),
                           top=KPI.top_projects(db, days), compact=compact)



@app.route("/admin")
@admin_required
def admin():
    """Page d'administration : chaque membre de l'equipe ne voit que les sections de son role."""
    db = get_db()
    q = request.args.get("q", "").strip().lower()
    stats, users, pending, disputes, sigs, journal = {}, [], [], [], [], []
    if can("accounts"):
        users = db.execute("SELECT * FROM users WHERE deleted = 0 AND (? = '' OR lower(name) LIKE ? OR lower(email) LIKE ? "
                           "OR phone LIKE ?) ORDER BY id DESC LIMIT 50", (q, f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        stats["users"] = db.execute("SELECT COUNT(*) FROM users WHERE deleted = 0").fetchone()[0]
        stats["proofs_bad"] = db.execute("SELECT COUNT(*) FROM proofs WHERE ok = 0 AND created_at >= ?",
                                         ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),)).fetchone()[0]
        stats["notif_fail"] = db.execute("SELECT COUNT(*) FROM notifications WHERE status = 'echec'").fetchone()[0]
    if can("accounts") or can("commerce"):
        stats["projects"] = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if can("money"):
        stats["escrow"] = db.execute("SELECT COALESCE(SUM(CASE WHEN kind = 'depot' AND status = 'reussi' THEN amount "
                                     "WHEN kind = 'versement' AND status != 'echoue' THEN -amount ELSE 0 END), 0) "
                                     "FROM transactions").fetchone()[0]
    if can("verify"):
        pending = db.execute("SELECT * FROM users WHERE (role IN ('inspecteur', 'fournisseur') OR (role = 'pro' AND profession IN "
                             "('ingenieur', 'bureau_controle')) OR ((role = 'chef' OR (role = 'pro' AND profession = 'entrepreneur')) "
                             "AND verify_requested = 1)) AND verified = 0 AND deleted = 0 AND blocked = 0 ORDER BY id").fetchall()
    if can("commerce"):
        stats["orders"] = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(received_total), 0) AS v, COALESCE(SUM(commission), 0) AS c "
                                     "FROM orders WHERE status IN ('receptionnee', 'a_payer')").fetchone()
        stats["orders_open"] = db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('proposee','envoyee','acceptee','livree')"
                                          ).fetchone()[0]
    if can("imagery"):
        stats["imagery"] = db.execute("SELECT o.*, p.name AS project_name, p.lat, p.lng FROM imagery_orders o JOIN projects p ON "
                                      "p.id = o.project_id WHERE o.status = 'demandee' ORDER BY o.id").fetchall()
    if can("disputes"):
        stats["orders_litige"] = db.execute("SELECT o.*, p.name AS project_name FROM orders o JOIN projects p ON "
                                            "p.id = o.project_id WHERE o.status = 'litige' ORDER BY o.id").fetchall()
        disputes = db.execute("SELECT d.*, p.name AS project_name FROM disputes d JOIN projects p ON p.id = d.project_id "
                              "ORDER BY d.status IN ('en_appel', 'ouvert') DESC, d.id DESC LIMIT 30").fetchall()
    if can("moderation"):
        sigs = db.execute("SELECT s.*, p.name AS project_name FROM signalements s JOIN projects p ON p.id = s.project_id "
                          "ORDER BY s.id DESC LIMIT 30").fetchall()
    if can("platform"):
        stats["escrow_on"] = escrow_enabled(db)
        stats["auto_on"], stats["auto_days"] = auto_validate_on(db), auto_validate_days(db)
        stats["quality_ai"] = get_setting("quality_ai", "1", db) == "1"
        age = backup_age_hours(db)
        stats["ops"] = {"age": age, "ok": get_setting("ops_backup_ok", None, db), "detail": get_setting("ops_backup_detail", "", db),
                        "error": get_setting("ops_backup_error", "", db), "remote": OFFSITE.configured(),
                        "remote_ok": get_setting("ops_offsite_ok", None, db), "remote_detail": get_setting("ops_offsite_detail", "", db),
                        "remote_error": get_setting("ops_offsite_error", "", db), "last": get_setting("ops_backup_last", None, db),
                        "daily": get_setting("ops_daily_last", None, db), "cron": bool(env("CRON_TOKEN")),
                        "disk": round(shutil.disk_usage(UPLOAD_DIR).free / 1e9, 1)}
        if age is None or age > 36 or stats["ops"]["ok"] == "0" or stats["ops"]["remote_ok"] == "0" or not stats["ops"]["remote"]:
            stats["ops"]["warn"] = True
        stats["quality_ai_key"] = QUAL.ai_enabled()
        stats["quality_month"] = db.execute("SELECT COUNT(*) FROM quality_reviews WHERE mode = 'ia' AND analysed_at LIKE ?",
                                            (QUAL.now_month() + "%",)).fetchone()[0]
        stats["auto_projects"] = db.execute("SELECT COUNT(*) FROM projects WHERE auto_validate = 1").fetchone()[0]
        stats["escrow_projects"] = db.execute("SELECT COUNT(*) FROM projects WHERE pay_mode = 'sequestre'").fetchone()[0]
        stats["escrow_changed"] = db.execute("SELECT s.updated_at, u.email FROM settings s LEFT JOIN users u ON u.id = s.updated_by "
                                             "WHERE s.key = 'escrow_enabled'").fetchone()
    if can("verify"):
        stats["land_requests"] = db.execute("SELECT r.*, p.name AS project_name, u.name AS owner_name, u.email AS owner_email, "
                                            "u.phone AS owner_phone, lf.doc_type, lf.title_ref FROM land_requests r "
                                            "JOIN projects p ON p.id = r.project_id JOIN users u ON u.id = r.user_id "
                                            "LEFT JOIN land_files lf ON lf.project_id = r.project_id WHERE r.status != 'faite' "
                                            "ORDER BY r.id").fetchall()
    if can("money"):
        subs = db.execute("SELECT * FROM subscriptions").fetchall()
        now = datetime.now(timezone.utc)
        prices = plan_prices(db)
        counts = {}
        mrr = 0
        for sb in subs:
            st = BILL.effective_status(sb, now)
            counts[st] = counts.get(st, 0) + 1
            if st in ("actif", "impaye") and sb["plan"] in BILL.PAID_PLANS:
                mrr += BILL.from_ttc(BILL.monthly_price(sb["plan"], prices, sb["custom_price"]) or 0, vat_rate(db))[0]
        stats["subs"] = counts
        stats["mrr"] = mrr
        stats["open_invoices"] = db.execute("SELECT i.*, u.name, u.email FROM billing_invoices i JOIN users u ON u.id = i.user_id "
                                            "WHERE i.status = 'a_payer' ORDER BY i.due_date").fetchall()
        stats["paid_invoices"] = db.execute("SELECT i.*, u.name FROM billing_invoices i JOIN users u ON u.id = i.user_id "
                                            "WHERE i.status = 'payee' ORDER BY i.paid_at DESC LIMIT 15").fetchall()
        stats["revenue_month"] = db.execute("SELECT COALESCE(SUM(amount_ht), 0) FROM billing_invoices WHERE status = 'payee' "
                                            "AND substr(paid_at, 1, 7) = ?", (now_iso()[:7],)).fetchone()[0]
    if can("platform"):
        stats["prices"] = {k: BILL.monthly_price(k, plan_prices(db)) for k in ("essentiel", "pro")}
        stats["vat_rate"] = vat_rate(db)
        stats["inspection_price"], stats["inspection_payout"] = inspection_prices(db)
        stats["seller"] = get_setting("billing_seller", "", db)
        stats["bank"] = get_setting("billing_bank", "", db)
    if can("money"):
        stats["month"] = request.args.get("mois") if re.fullmatch(r"\d{4}-\d{2}", request.args.get("mois", "")) \
            else now_iso()[:7]
        stats["commissions"] = supplier_commissions(db, stats["month"])
    if can("inspections"):
        stats["insp_requests"] = db.execute("SELECT r.*, p.name AS project_name, p.address, p.commune, s.name AS step_name "
                                            "FROM inspection_requests r JOIN projects p ON p.id = r.project_id LEFT JOIN steps s "
                                            "ON s.id = r.step_id WHERE r.status = 'a_attribuer' ORDER BY r.id").fetchall()
        stats["inspectors"] = db.execute("SELECT id, name, zone, phone FROM users WHERE role = 'inspecteur' AND verified = 1 "
                                         "AND blocked = 0 AND deleted = 0 ORDER BY zone, name").fetchall()
    if can("money"):
        stats["insp_payouts"] = db.execute("SELECT i.*, u.name AS inspector_name, u.phone AS inspector_phone, p.name AS project_name "
                                           "FROM inspections i JOIN users u ON u.id = i.inspector_id JOIN projects p ON "
                                           "p.id = i.project_id WHERE i.sold = 1 AND i.payout_status = 'a_verser' ORDER BY i.id"
                                           ).fetchall()
    if can("journal"):
        journal = db.execute("SELECT l.*, u.email FROM admin_log l JOIN users u ON u.id = l.admin_id ORDER BY l.id DESC "
                             "LIMIT 30").fetchall()
    todo = []                                    # ce qui attend une action, en tete de page
    if can("verify") and pending:
        todo.append((_("Comptes à vérifier"), len(pending), "verifier"))
    if can("verify") and stats.get("land_requests"):
        todo.append((_("Vérifications foncières demandées"), len(stats["land_requests"]), "foncier"))
    if can("inspections") and stats.get("insp_requests"):
        todo.append((_("Inspections à attribuer"), len(stats["insp_requests"]), "inspections"))
    if can("disputes"):
        n_open = len([x for x in disputes if (x["stage"] if "stage" in x.keys() else "") not in ("clos", "resolu")])
        if n_open:
            todo.append((_("Litiges à suivre"), n_open, "litiges"))
    if can("moderation"):
        n_sig = len([x for x in sigs if x["status"] == "nouveau"])
        if n_sig:
            todo.append((_("Signalements citoyens à traiter"), n_sig, "moderation"))
    if can("money"):
        n_inv = db.execute("SELECT COUNT(*) FROM billing_invoices WHERE status = 'a_payer'").fetchone()[0]
        if n_inv:
            todo.append((_("Factures d'abonnement à encaisser"), n_inv, "abonnements"))
        if stats.get("insp_payouts"):
            todo.append((_("Inspecteurs à payer"), len(stats["insp_payouts"]), "inspections"))
    o = stats.get("ops")
    if o and (o["ok"] == "0" or o["remote_ok"] == "0" or (o["age"] is not None and o["age"] > 36)):
        todo.append((_("Sauvegardes à vérifier"), 1, "exploitation"))
    return render_template("admin.html", users=users, stats=stats, pending=pending, disputes=disputes, sigs=sigs, q=q, todo=todo,
                           journal=journal, my_role=staff_role(current_user()), SUB_STATUS=tr(BILL.SUB_STATUS),
                           INV_METHODS=tr(BILL.INV_METHODS),
                           reset_link=session.pop("admin_reset_link", None))


def supplier_commissions(db, month):
    """Commissions a facturer aux fournisseurs pour les commandes payees hors sequestre (le mois de reception)."""
    return db.execute("SELECT u.id, u.name, u.company, u.email, COUNT(*) AS n, COALESCE(SUM(o.received_total), 0) AS sales, "
                      "COALESCE(SUM(o.commission), 0) AS commission, "
                      "SUM(CASE WHEN o.status = 'receptionnee' THEN 1 ELSE 0 END) AS paid "
                      "FROM orders o JOIN users u ON u.id = o.supplier_id WHERE o.pay_mode != 'sequestre' "
                      "AND o.status IN ('a_payer', 'receptionnee') AND substr(o.received_at, 1, 7) = ? "
                      "GROUP BY u.id, u.name, u.company, u.email ORDER BY commission DESC", (month,)).fetchall()


@app.route("/admin/commissions.csv")
@admin_required(perm="money")
def commissions_csv():
    month = request.args.get("mois", "")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        month = now_iso()[:7]
    db = get_db()
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow([_("Mois"), _("Fournisseur"), _("Entreprise"), _("E-mail"), _("Commandes"), _("Ventes (FCFA)"),
                _("Commission à facturer (FCFA)"), _("Commandes payées et confirmées")])
    for r in supplier_commissions(db, month):
        w.writerow([month, r["name"], r["company"] or "", r["email"], r["n"], r["sales"], r["commission"], r["paid"]])
    staff_log(db, current_user(), f"commissions_csv:{month}")
    db.commit()
    resp = app.response_class("\ufeff" + out.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="commissions-fournisseurs-{month}.csv"'
    return resp


@app.route("/admin/abonnements", methods=["POST"])
@admin_required
def admin_billing():
    """Finance : valider un paiement recu hors ligne, annuler une facture. Super-admin : tarifs et offres sur mesure."""
    db = get_db()
    me = current_user()
    f = request.form
    action = f.get("action")
    back = redirect(url_for("admin", _anchor="abonnements"))
    if action in ("inv_paid", "inv_cancel"):
        if not can("money", me):
            abort(403)
        inv = db.execute("SELECT * FROM billing_invoices WHERE id = ?", (to_int(f.get("id")),)).fetchone()
        if inv is None or inv["status"] != "a_payer":
            abort(404)
        if action == "inv_paid":
            method = f.get("method") if f.get("method") in BILL.INV_METHODS else "virement"
            ref = f.get("reference", "").strip()[:80]
            if not ref and method != "offert":
                flash(_("Indiquez la référence du virement ou du reçu."), "error")
                return back
            invoice_paid(db, inv, method, ref or None)
        else:
            db.execute("UPDATE billing_invoices SET status = 'annulee' WHERE id = ?", (inv["id"],))
        staff_log(db, me, f"{action}:{inv['number']}", inv["user_id"])
    elif action == "prices":
        if not can("platform", me):
            abort(403)
        prices = {k: to_int(f.get(f"price_{k}")) for k in ("essentiel", "pro") if to_int(f.get(f"price_{k}")) > 0}
        set_setting(db, "plan_prices", json.dumps(prices), me["id"])
        rate = to_float(f.get("vat_rate")) or 0
        set_setting(db, "vat_rate", str(min(max(rate, 0), 50)), me["id"])
        for key in ("inspection_price", "inspection_payout"):
            if to_int(f.get(key)) > 0:
                set_setting(db, key, str(to_int(f.get(key))), me["id"])
        set_setting(db, "billing_seller", f.get("seller", "").strip()[:500], me["id"])
        set_setting(db, "billing_bank", f.get("bank", "").strip()[:500], me["id"])
        staff_log(db, me, "billing_settings")
    elif action == "custom":
        if not can("platform", me):
            abort(403)
        u = db.execute("SELECT * FROM users WHERE email = ? AND deleted = 0 AND role = 'proprio'",
                       (f.get("email", "").strip().lower(),)).fetchone()
        if not u:
            flash(_("Aucun propriétaire avec cet e-mail."), "error")
            return back
        sub = get_sub(db, u)
        plan = f.get("plan") if f.get("plan") in BILL.PAID_PLANS else "entreprise"
        price = to_int(f.get("price")) or None
        limit = to_int(f.get("sites")) or None
        months = min(to_int(f.get("months")), 36)
        db.execute("UPDATE subscriptions SET plan = ?, custom_price = ?, sites_limit = ?, updated_at = ? WHERE id = ?",
                   (plan, price, limit, now_iso(), sub["id"]))
        if months > 0:
            now = datetime.now(timezone.utc)
            start = now
            if sub["status"] in ("actif", "impaye") and sub["period_end"] and datetime.fromisoformat(sub["period_end"]) > now:
                start = datetime.fromisoformat(sub["period_end"])
            end = BILL.add_months(start, months)
            db.execute("UPDATE subscriptions SET status = 'actif', period_start = COALESCE(period_start, ?), period_end = ?, "
                       "cycle = 'mois' WHERE id = ?", (now.isoformat(), end.isoformat(), sub["id"]))
            notify(None, [u["id"]], L("Abonnement mis à jour"),
                   L("Votre abonnement %(plan)s est actif jusqu'au %(d)s.", plan=L(BILL.PLANS[plan]["label"]),
                     d=format_d(end.isoformat())), "/compte/abonnement", important=True, db=db)
        staff_log(db, me, f"sub_custom:{plan}:{price or '-'}:{limit or '-'}:{months}m", u["id"])
    else:
        abort(400)
    db.commit()
    flash(_("Action effectuée."), "ok")
    return back


# Action -> permission requise. block/unblock : support, ou verification pour refuser un dossier en attente.
ADMIN_ACTION_PERM = {"verify": "verify", "unverify": "verify", "block": "accounts", "unblock": "accounts",
                     "reset_link": "recovery", "disable_2fa": "recovery", "hide_sig": "moderation", "show_sig": "moderation",
                     "escrow_on": "platform", "escrow_off": "platform", "auto_validate": "platform", "quality_ai": "platform", "land_request": "verify"}


@app.route("/admin/action", methods=["POST"])
@admin_required
def admin_action():
    db = get_db()
    f = request.form
    action = f.get("action")
    target = to_int(f.get("id"))
    me = current_user()
    if action not in ADMIN_ACTION_PERM:
        abort(400)
    allowed = can(ADMIN_ACTION_PERM[action], me)
    if not allowed and action == "block" and can("verify", me):
        tu = db.execute("SELECT * FROM users WHERE id = ?", (target,)).fetchone()
        allowed = bool(tu and tu["role"] in ("inspecteur", "fournisseur", "pro", "chef") and not tu["verified"]
                       and not tu["is_admin"])
    if not allowed:
        abort(403)
    if action in ("verify", "unverify"):
        db.execute("UPDATE users SET verified = ? WHERE id = ? AND role IN ('inspecteur', 'fournisseur', 'pro', 'chef')",
                   (int(action == "verify"), target))
        tu = db.execute("SELECT * FROM users WHERE id = ?", (target,)).fetchone()
        if action == "verify" and tu and is_contractor(tu):
            notify(None, [target], L("Entreprise vérifiée"),
                   L("Votre profil d'entrepreneur vérifié apparaît dans l'annuaire : les propriétaires peuvent vous inviter."),
                   f"/entrepreneurs/{target}", important=True)
        elif action == "verify" and tu and tu["role"] == "pro":
            notify(None, [target], L("Qualifications vérifiées"),
                   L("Vous pouvez être ajouté aux chantiers comme ingénieur ou bureau de contrôle et valider des contrôles."), "/",
                   important=True)
        elif action == "verify" and tu and tu["role"] == "fournisseur":
            notify(None, [target], L("Entreprise vérifiée"), L('Votre catalogue est maintenant proposé aux chantiers.'),
                   "/fournisseur/catalogue", important=True)
        elif action == "verify":
            notify(None, [target], L("Profil d'inspecteur vérifié"), L('Vous êtes maintenant proposé aux propriétaires.'), "/",
                   important=True)
    elif action in ("block", "unblock"):
        tu = db.execute("SELECT * FROM users WHERE id = ?", (target,)).fetchone()
        if target == me["id"] or (tu and staff_role(tu) == "super" and staff_role(me) != "super"):
            abort(403)
        db.execute("UPDATE users SET blocked = ?, session_version = session_version + 1 WHERE id = ?",
                   (int(action == "block"), target))
    elif action == "reset_link":
        u = db.execute("SELECT * FROM users WHERE id = ? AND deleted = 0", (target,)).fetchone()
        if u:
            session["admin_reset_link"] = (u["name"], request.host_url.rstrip("/") + create_reset_link(db, u))
    elif action == "disable_2fa":
        db.execute("UPDATE users SET totp_on = 0, totp_secret = NULL, backup_codes = NULL WHERE id = ?", (target,))
    elif action in ("hide_sig", "show_sig"):
        db.execute("UPDATE signalements SET hidden = ?, status = CASE WHEN ? = 1 THEN 'rejete' WHEN status = 'rejete' "
                   "THEN 'nouveau' ELSE status END, moderation_note = ? WHERE id = ?",
                   (int(action == "hide_sig"), int(action == "hide_sig"), f.get("note", "").strip()[:300] or None, target))
    elif action == "escrow_on":
        if not f.get("partner", "").strip() or not f.get("confirm"):
            flash(_("Indiquez le partenaire agréé qui garde les fonds et cochez la confirmation."), "error")
            return redirect(url_for("admin", _anchor="plateforme"))
        set_setting(db, "escrow_enabled", "1", me["id"])
        set_setting(db, "escrow_partner", f.get("partner").strip()[:150], me["id"])
    elif action == "escrow_off":
        set_setting(db, "escrow_enabled", "0", me["id"])
    elif action == "land_request":
        lr = db.execute("SELECT * FROM land_requests WHERE id = ?", (target,)).fetchone()
        if lr:
            st_ = f.get("status") if f.get("status") in ("en_cours", "faite") else "en_cours"
            db.execute("UPDATE land_requests SET status = ?, result = ?, handled_by = ?, handled_at = ? WHERE id = ?",
                       (st_, f.get("result", "").strip()[:2000] or lr["result"], me["id"], now_iso(), target))
            notify(lr["project_id"], [lr["user_id"]], L("Vérification foncière"),
                   L("Votre demande de vérification du terrain est %(s)s.", s=L("terminée") if st_ == "faite" else L("prise en charge")),
                   f"/chantiers/{lr['project_id']}/foncier", important=st_ == "faite")
    elif action == "quality_ai":
        set_setting(db, "quality_ai", "1" if f.get("on") else "0", me["id"])
    elif action == "auto_validate":
        set_setting(db, "auto_validate_enabled", "1" if f.get("on") else "0", me["id"])
        set_setting(db, "auto_validate_days", str(min(max(to_int(f.get("days")) or AUTO_VALIDATE_DAYS, 5), 30)), me["id"])
    staff_log(db, me, action, target)
    db.commit()
    flash(_('Action effectuée.'), "ok")
    return redirect(url_for("admin", q=f.get("q", "")))


@app.route("/admin/equipe", methods=["GET", "POST"])
@admin_required(perm="team")
def staff_team():
    """Comptes de l'equipe ChantierVrai : inviter, changer de role, retirer l'acces."""
    db = get_db()
    me = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        role = request.form.get("role")
        if action == "add":
            email = request.form.get("email", "").strip().lower()
            u = db.execute("SELECT * FROM users WHERE email = ? AND deleted = 0", (email,)).fetchone()
            if role not in STAFF_ROLES:
                abort(400)
            if not u:
                flash(_("Aucun compte avec cet e-mail. La personne crée d'abord son compte, puis vous lui donnez un rôle."),
                      "error")
                return redirect(url_for("staff_team"))
            if u["blocked"]:
                flash(_("Ce compte est bloqué. Débloquez-le avant de l'ajouter à l'équipe."), "error")
                return redirect(url_for("staff_team"))
            db.execute("UPDATE users SET is_admin = 1, staff_role = ? WHERE id = ?", (role, u["id"]))
            staff_log(db, me, f"team_add:{role}", u["id"])
            notify(None, [u["id"]], L("Accès équipe ChantierVrai"),
                   L("Vous avez rejoint l'équipe (%(r)s). Activez la double authentification pour ouvrir l'administration.",
                     r=STAFF_ROLES[role]), "/compte/securite", important=True, db=db)
            flash(_("%(n)s a rejoint l'équipe.", n=u["name"]), "ok")
        else:
            target = to_int(request.form.get("id"))
            u = db.execute("SELECT * FROM users WHERE id = ? AND is_admin = 1", (target,)).fetchone()
            if not u:
                abort(404)
            if u["id"] == me["id"]:
                flash(_("Vous ne pouvez pas changer votre propre accès. Demandez à un autre super-admin."), "error")
                return redirect(url_for("staff_team"))
            if action == "role":
                if role not in STAFF_ROLES:
                    abort(400)
                db.execute("UPDATE users SET staff_role = ? WHERE id = ?", (role, u["id"]))
                staff_log(db, me, f"team_role:{role}", u["id"])
                flash(_("Rôle modifié."), "ok")
            elif action == "remove":
                db.execute("UPDATE users SET is_admin = 0, staff_role = NULL, session_version = session_version + 1 "
                           "WHERE id = ?", (u["id"],))
                staff_log(db, me, "team_remove", u["id"])
                flash(_("Accès équipe retiré. Ses sessions sont déconnectées."), "ok")
            else:
                abort(400)
        db.commit()
        return redirect(url_for("staff_team"))
    team = db.execute("SELECT * FROM users WHERE is_admin = 1 AND deleted = 0 ORDER BY id").fetchall()
    last = {r["admin_id"]: r["m"] for r in db.execute("SELECT admin_id, MAX(created_at) AS m FROM admin_log GROUP BY admin_id")}
    return render_template("staff_team.html", team=team, last=last, staff_role=staff_role,
                           help=tr(STAFF_ROLE_HELP), need_2fa=staff_2fa_required())


@app.cli.command("creer-admin")
@click.argument("email")
@click.option("--role", default="super", type=click.Choice(list(STAFF_ROLES)), help="Rôle dans l'équipe")
def create_admin_cli(email, role):
    """Donne un acces equipe (super-admin par defaut) a un compte existant."""
    db = connect()
    n = db.execute("UPDATE users SET is_admin = 1, staff_role = ? WHERE email = ?", (role, email.strip().lower())).rowcount
    db.commit()
    db.close()
    print("Administrateur ajouté." if n else "Aucun compte avec cet e-mail. Créez d'abord le compte dans l'application.")


# --------------------------------------------------------------------------
# Fiche du projet : type, surfaces, foncier, parcelle dessinee
# --------------------------------------------------------------------------
@app.route("/chantiers/<int:project_id>/fiche", methods=["GET", "POST"])
@login_required
def project_sheet(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    db = get_db()
    if request.method == "POST":
        if g.project_role != "owner":
            abort(403)
        f = request.form
        btype = f.get("building_type") or None
        if btype and btype not in BUILDING_TYPES:
            abort(400)
        parcel_raw = (f.get("parcel") or "").strip()
        parcel = None
        if parcel_raw:
            pts = GEO.parse(parcel_raw)
            if not pts:
                flash(_("Parcelle invalide : dessinez au moins trois points."), "error")
                return redirect(url_for("project_sheet", project_id=project_id))
            far = max(haversine(a, b, p["lat"], p["lng"]) for a, b in pts)
            if far > 5000:
                flash(_("La parcelle est à plus de 5 km du chantier : vérifiez son emplacement."), "error")
                return redirect(url_for("project_sheet", project_id=project_id))
            parcel = json.dumps([[round(a, 7), round(b, 7)] for a, b in pts])
        levels = to_int(f.get("levels"), None)
        db.execute("UPDATE projects SET building_type = ?, levels = ?, surface_land = ?, surface_floor = ?, land_title = ?, "
                   "land_ref = ?, commune = ?, permit_ref = ?, parcel = ?, description = ? WHERE id = ?",
                   (btype, levels if levels is None else max(0, min(levels, 80)), to_float(f.get("surface_land")),
                    to_float(f.get("surface_floor")), f.get("land_title", "").strip()[:120] or None,
                    f.get("land_ref", "").strip()[:120] or None, f.get("commune", "").strip()[:80] or None,
                    f.get("permit_ref", "").strip()[:80] or None, parcel, f.get("description", "").strip()[:2000] or None,
                    project_id))
        if (parcel or None) != (p["parcel"] or None):
            log(project_id, L("Parcelle dessinée : %(v)s m², les photos sont contrôlées sur la parcelle", v=round(GEO.area_m2(GEO.parse(parcel))))
                if parcel else L("Parcelle retirée : les photos sont contrôlées sur le rayon autour du point"))
        log(project_id, L("Fiche du projet mise à jour"))
        db.commit()
        flash(_("Fiche du projet enregistrée."), "ok")
        return redirect(url_for("project_sheet", project_id=project_id))
    s = project_stats(project_id)
    pts = GEO.parse(p["parcel"]) if p["parcel"] else None
    people = {"chef": db.execute("SELECT name, phone FROM users WHERE id = ?", (p["chef_id"],)).fetchone() if p["chef_id"] else None,
              "owner": db.execute("SELECT name FROM users WHERE id = ?", (p["owner_id"],)).fetchone(),
              "members": db.execute("SELECT u.name, u.email, m.role FROM project_members m JOIN users u ON u.id = m.user_id "
                                    "WHERE m.project_id = ? ORDER BY m.role", (project_id,)).fetchall(),
              "inspectors": db.execute("SELECT DISTINCT u.name FROM inspections i JOIN users u ON u.id = i.inspector_id "
                                       "WHERE i.project_id = ? AND i.status IN ('acceptee', 'realisee')", (project_id,)).fetchall(),
              "suppliers": db.execute("SELECT DISTINCT u.name FROM orders o JOIN users u ON u.id = o.supplier_id "
                                      "WHERE o.project_id = ? AND o.status NOT IN ('refusee', 'annulee')", (project_id,)).fetchall()}
    plans = db.execute("SELECT * FROM documents WHERE project_id = ? AND category IN ('Plan', 'Permis de construire') "
                       "ORDER BY id DESC", (project_id,)).fetchall()
    return render_template("project_sheet.html", p=p, s=s, role=g.project_role, parcel=pts,
                           parcel_area=round(GEO.area_m2(pts)) if pts else None, people=people, plans=plans,
                           pred=project_prediction(p, s), BUILDING_TYPES=tr(BUILDING_TYPES),
                           schedule=PRED.step_schedule(p, s["steps"]), tolerance=PARCEL_TOLERANCE)


@app.route("/chantiers/<int:project_id>/export-comptable.csv")
@login_required
def accounting_export(project_id):
    """Ecritures du chantier pour le logiciel comptable : depots, paiements d'etapes, achats de materiaux, factures."""
    p = load_project(project_id, roles=("owner", "intervenant", "admin"))
    if g.project_role == "intervenant" and not member_can("export"):
        abort(403)
    db = get_db()
    rows = []
    for t in db.execute("SELECT t.*, st.name AS step_name, o.ref AS order_ref FROM transactions t LEFT JOIN steps st ON "
                        "st.id = t.step_id LEFT JOIN orders o ON o.id = t.order_id WHERE t.project_id = ? ORDER BY t.id",
                        (project_id,)):
        if t["status"] not in ("reussi", "en_attente"):
            continue
        label = (_("Dépôt sur le séquestre") if t["kind"] == "depot" else
                 _("Achat de matériaux %(ref)s", ref=t["order_ref"]) if t["order_ref"] else
                 _("Paiement d'étape : %(s)s", s=t["step_name"]) if t["step_name"] else _("Versement"))
        rows.append((t["created_at"][:10], "banque", label, t["step_name"] or "", t["amount"] if t["kind"] == "depot" else -t["amount"],
                     t["provider_ref"] or t["ref"], t["status"]))
    for r in db.execute("SELECT * FROM payment_records WHERE project_id = ? AND status IN ('declare', 'confirme') ORDER BY id",
                        (project_id,)):
        due = payment_due(db, r["kind"], r["ref_id"])
        rows.append((r["paid_on"] or r["created_at"][:10], "paiement", I18N.render(due["label"]),
                     due["item"]["name"] if r["kind"] == "etape" else "", -r["amount"],
                     r["reference"] or due["ref"], "paye" if r["status"] == "confirme" else "declare"))
    for st in db.execute("SELECT * FROM steps WHERE project_id = ? AND status IN ('paye', 'versement') ORDER BY position",
                         (project_id,)):
        if p["pay_mode"] == "manuel":
            rows.append(((st["paid_at"] or "")[:10], "paiement", _("Paiement d'étape : %(s)s", s=st["name"]), st["name"],
                         -st["amount"], st["pay_ref"] or "", "paye"))
    for inv in db.execute("SELECT i.*, st.name AS step_name FROM invoices i LEFT JOIN steps st ON st.id = i.step_id "
                          "WHERE i.project_id = ? AND i.status IN ('validee', 'a_verifier') ORDER BY i.id", (project_id,)):
        rows.append(((inv["inv_date"] or inv["created_at"])[:10], "facture", _("Facture %(n)s de %(s)s", n=inv["number"] or "",
                                                                              s=inv["supplier"] or "?"),
                     inv["step_name"] or "", -(inv["total"] or 0), inv["number"] or "", inv["status"]))
    rows.sort(key=lambda r: r[0])
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow([_("Date"), _("Journal"), _("Libellé"), _("Étape"), _("Montant (FCFA)"), _("Référence"), _("Statut")])
    w.writerows(rows)
    resp = app.response_class("﻿" + out.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="chantier-{project_id}-comptabilite.csv"'
    return resp


# --------------------------------------------------------------------------
# Maquette numerique (BIM / IFC) : niveaux, elements, versions, avancement par niveau
# --------------------------------------------------------------------------
BIM_DIR = os.path.join(UPLOAD_DIR, "bim")
os.makedirs(BIM_DIR, exist_ok=True)
BIM_MAX = 80 * 1024 * 1024


def bim_can_edit(role):
    return role == "owner" or (role in ("intervenant", "inspecteur") and member_can("maquette"))


def storey_status(st):
    """Etat d'un niveau d'apres l'etape liee : construit, a valider, en cours, a venir."""
    if st is None:
        return "none"
    return {"paye": "done", "versement": "done", "declare": "declared", "en_cours": "doing"}.get(st["status"], "todo")


@app.route("/chantiers/<int:project_id>/maquette", methods=["GET", "POST"])
@login_required
def bim(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    back = redirect(url_for("bim", project_id=project_id))
    if request.method == "POST":
        action = request.form.get("action", "upload")
        if action == "link":
            if role != "owner":
                abort(403)
            for k, v in request.form.items():
                if k.startswith("storey_"):
                    name = k[7:]
                    sid = to_int(v, None)
                    if sid:
                        get_step(project_id, sid)
                    db.execute("INSERT INTO bim_storeys (project_id, storey, step_id) VALUES (?,?,?) ON CONFLICT "
                               "(project_id, storey) DO UPDATE SET step_id = excluded.step_id", (project_id, name, sid))
            db.commit()
            flash(_("Niveaux reliés aux étapes."), "ok")
            return back
        if not bim_can_edit(role):
            abort(403)
        file = request.files.get("file")
        if not file or not file.filename or ext_of(file.filename) != "ifc":
            flash(_("Choisissez un fichier IFC (export de Revit, ArchiCAD, Allplan, BlenderBIM…)."), "error")
            return back
        raw = file.read(BIM_MAX + 1)
        if len(raw) > BIM_MAX:
            flash(_("Maquette trop lourde (80 Mo maximum)."), "error")
            return back
        try:
            summary = IFC.parse(raw)
        except Exception:
            flash(_("Ce fichier n'est pas une maquette IFC lisible."), "error")
            return back
        version = (db.execute("SELECT MAX(version) FROM bim_models WHERE project_id = ?", (project_id,)).fetchone()[0] or 0) + 1
        name = f"{secrets.token_hex(12)}.ifc"
        with open(os.path.join(BIM_DIR, name), "wb") as fh:
            fh.write(raw)
        db.execute("INSERT INTO bim_models (project_id, user_id, version, filename, original_name, summary, note, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?)", (project_id, current_user()["id"], version, name, file.filename[:150],
                                                json.dumps(summary, ensure_ascii=False),
                                                request.form.get("note", "").strip()[:300] or None, now_iso()))
        # liaison automatique niveau -> etape quand les noms se ressemblent
        linked = {r["storey"] for r in db.execute("SELECT storey FROM bim_storeys WHERE project_id = ?", (project_id,))}
        for stry in summary["storeys"]:
            if stry["name"] in linked:
                continue
            words = set(MAT.plain(stry["name"]).replace("-", " ").split()) - {"de", "du", "la", "le", "niveau"}
            match = next((st for st in steps if words & set(MAT.plain(st["name"]).replace("-", " ").split())), None)
            if match:
                db.execute("INSERT INTO bim_storeys (project_id, storey, step_id) VALUES (?,?,?)", (project_id, stry["name"], match["id"]))
        log(project_id, L("Maquette numérique version %(v)s : %(n)s niveau(x), %(e)s éléments", v=version,
                          n=len(summary["storeys"]), e=sum(summary["totals"].values())))
        if version > 1:
            notify(project_id, owners_of(p, db) + ([p["chef_id"]] if p["chef_id"] else []), L("Nouvelle version de la maquette"),
                   L("Version %(v)s de la maquette du chantier %(p)s : regardez les modifications.", v=version, p=p["name"]),
                   url_for("bim", project_id=project_id), db=db)
        db.commit()
        flash(_("Maquette enregistrée."), "ok")
        return back
    models = db.execute("SELECT b.*, u.name AS author FROM bim_models b JOIN users u ON u.id = b.user_id WHERE b.project_id = ? "
                        "ORDER BY b.version DESC", (project_id,)).fetchall()
    cur = json.loads(models[0]["summary"]) if models else None
    changes = IFC.diff(json.loads(models[1]["summary"]), cur) if len(models) > 1 else []
    links = {r["storey"]: r["step_id"] for r in db.execute("SELECT * FROM bim_storeys WHERE project_id = ?", (project_id,))}
    by_id = {st["id"]: st for st in steps}
    rows = []
    for stry in (cur["storeys"] if cur else []):
        st = by_id.get(links.get(stry["name"]))
        rows.append({"s": stry, "step": st, "state": storey_status(st)})
    built = sum(1 for r in rows if r["state"] == "done")
    plans_3d = db.execute("SELECT * FROM media3d WHERE project_id = ? AND kind = 'modele3d' ORDER BY id DESC", (project_id,)).fetchall()
    return render_template("bim.html", p=p, role=role, models=models, cur=cur, rows=rows, changes=changes, steps=steps,
                           can_edit=bim_can_edit(role), built=built, plans_3d=plans_3d,
                           ELEMENTS=sorted(set(IFC.ELEMENTS.values())))


@app.route("/maquettes/<int:model_id>")
@login_required
def bim_file(model_id):
    m = get_db().execute("SELECT * FROM bim_models WHERE id = ?", (model_id,)).fetchone()
    if m is None:
        abort(404)
    load_project(m["project_id"], roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    return send_from_directory(BIM_DIR, m["filename"], as_attachment=True,
                               download_name=m["original_name"] or f"maquette-v{m['version']}.ifc")


# --------------------------------------------------------------------------
# Capteurs connectes et station meteo
# --------------------------------------------------------------------------
SENSOR_KINDS = {
    "humidite": ("Humidité", "%", None, 85), "vibration": ("Vibration", "mm/s", None, 10),
    "deformation": ("Déformation (fissuromètre, inclinomètre)", "mm", -2, 2), "mouvement": ("Détection de mouvement", "détections", None, 0),
    "temperature": ("Température", "°C", None, 40), "pluie": ("Pluie", "mm", None, 30), "vent": ("Vent", "km/h", None, 60),
    "autre": ("Autre mesure", "", None, None),
}


def sensors_can_edit(role):
    return role == "owner" or (role in ("intervenant", "inspecteur") and member_can("capteurs"))


def record_reading(db, sensor, value, at=None):
    """Enregistre une mesure et alerte quand elle sort des seuils (une alerte par passage en alarme)."""
    at = at or now_iso()
    db.execute("INSERT INTO sensor_readings (sensor_id, value, measured_at) VALUES (?,?,?)", (sensor["id"], value, at))
    out = (sensor["min_value"] is not None and value < sensor["min_value"]) or \
          (sensor["max_value"] is not None and value > sensor["max_value"])
    db.execute("UPDATE sensors SET last_value = ?, last_at = ?, alarm = ? WHERE id = ?", (value, at, int(out), sensor["id"]))
    if out and not sensor["alarm"]:
        p = db.execute("SELECT * FROM projects WHERE id = ?", (sensor["project_id"],)).fetchone()
        emit_event(db, p["id"], "anomalie", {"type": "capteur", "capteur": sensor["name"], "valeur": value, "unite": sensor["unit"],
                                             "min": sensor["min_value"], "max": sensor["max_value"]})
        ids = owners_of(p, db) + ([p["chef_id"]] if p["chef_id"] else []) + controllers_of(db, p)
        notify(p["id"], ids, L("Alerte capteur : %(n)s", n=sensor["name"]),
               L("%(n)s : %(v)s %(u)s, hors des seuils fixés. Vérifiez le chantier.", n=sensor["name"], v=fmt_qty(value),
                 u=sensor["unit"] or ""), f"/chantiers/{p['id']}/capteurs", important=True, db=db)
        db.execute("INSERT INTO activity (project_id, user_id, text, created_at) VALUES (?,?,?,?)",
                   (p["id"], None, I18N.store(L("Alerte capteur %(n)s : %(v)s %(u)s", n=sensor["name"], v=fmt_qty(value),
                                                 u=sensor["unit"] or "")), now_iso()))
    return out


@app.route("/chantiers/<int:project_id>/capteurs", methods=["GET", "POST"])
@login_required
def sensors_page(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    if request.method == "POST":
        if not sensors_can_edit(role):
            abort(403)
        f = request.form
        action = f.get("action")
        if action == "add":
            kind = f.get("kind")
            if kind not in SENSOR_KINDS or not f.get("name", "").strip():
                flash(_("Indiquez le type et le nom du capteur."), "error")
            else:
                label, unit, dmin, dmax = SENSOR_KINDS[kind]
                mn, mx = to_float(f.get("min_value")), to_float(f.get("max_value"))
                db.execute("INSERT INTO sensors (project_id, kind, name, unit, token, min_value, max_value, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (project_id, kind, f["name"].strip()[:80], f.get("unit", "").strip()[:12] or unit,
                                                        secrets.token_urlsafe(24), dmin if mn is None and f.get("min_value") is None else mn,
                                                        dmax if mx is None and f.get("max_value") is None else mx, now_iso()))
                log(project_id, L("Capteur ajouté : %(n)s", n=f["name"].strip()[:80]))
                db.commit()
                flash(_("Capteur ajouté. Configurez-le avec l'adresse et la clé affichées."), "ok")
        elif action in ("delete", "seuils", "mesure"):
            sn = db.execute("SELECT * FROM sensors WHERE id = ? AND project_id = ?", (to_int(f.get("sensor_id")), project_id)).fetchone()
            if sn is None:
                abort(404)
            if action == "delete":
                db.execute("DELETE FROM sensors WHERE id = ?", (sn["id"],))
            elif action == "seuils":
                db.execute("UPDATE sensors SET min_value = ?, max_value = ? WHERE id = ?",
                           (to_float(f.get("min_value")), to_float(f.get("max_value")), sn["id"]))
            else:
                v = to_float(f.get("value"))
                if v is None:
                    flash(_("Indiquez la valeur relevée."), "error")
                    return redirect(url_for("sensors_page", project_id=project_id))
                record_reading(db, sn, v)
            db.commit()
        return redirect(url_for("sensors_page", project_id=project_id))
    sensors = db.execute("SELECT * FROM sensors WHERE project_id = ? ORDER BY kind, name", (project_id,)).fetchall()
    series = {}
    for sn in sensors:
        rows = db.execute("SELECT value, measured_at FROM sensor_readings WHERE sensor_id = ? ORDER BY id DESC LIMIT 48",
                          (sn["id"],)).fetchall()
        series[sn["id"]] = [r["value"] for r in reversed(rows)]
    return render_template("sensors.html", p=p, role=role, sensors=sensors, series=series, can_edit=sensors_can_edit(role),
                           KINDS={k: (_(v[0]), v[1], v[2], v[3]) for k, v in SENSOR_KINDS.items()},
                           api_url=public_url("/api/v1/capteurs/mesures") or request.host_url.rstrip("/") + "/api/v1/capteurs/mesures",
                           meteo=WEATHER.enabled())


@app.route("/api/v1/capteurs/mesures", methods=["POST"])
def sensor_ingest():
    """Les capteurs envoient leurs mesures avec leur cle : {"value": 12.5} ou {"readings": [{"value": .., "at": ..}]}."""
    token = request.headers.get("X-Sensor-Key") or request.args.get("cle") or ""
    db = get_db()
    sn = db.execute("SELECT * FROM sensors WHERE token = ?", (token,)).fetchone() if token else None
    if sn is None:
        return jsonify(ok=False, error="unknown sensor key"), 401
    data = request.get_json(silent=True) or {}
    readings = data.get("readings") or ([{"value": data.get("value"), "at": data.get("at")}] if "value" in data else [])
    n = alarms = 0
    for r in readings[:500]:
        try:
            v = float(r.get("value"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(v):
            continue
        at = r.get("at")
        try:
            at = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds") if at else None
        except ValueError:
            at = None
        alarms += record_reading(db, db.execute("SELECT * FROM sensors WHERE id = ?", (sn["id"],)).fetchone(), v, at)
        n += 1
    db.commit()
    return jsonify(ok=True, received=n, alarms=alarms)


def daily_weather(db):
    """Releve meteo de la veille pour chaque chantier en cours (si METEO_AUTO=1)."""
    if not WEATHER.enabled():
        return 0
    n = 0
    for p in db.execute("SELECT * FROM projects WHERE id IN (SELECT project_id FROM steps WHERE status IN "
                        "('en_cours', 'declare'))").fetchall():
        try:
            day, vals = WEATHER.yesterday(p["lat"], p["lng"])
        except Exception:
            continue
        for kind, v in vals.items():
            if v is None:
                continue
            sn = db.execute("SELECT * FROM sensors WHERE project_id = ? AND kind = ? AND name LIKE 'Météo%'", (p["id"], kind)).fetchone()
            if sn is None:
                label, unit, mn, mx = SENSOR_KINDS[kind]
                db.execute("INSERT INTO sensors (project_id, kind, name, unit, token, min_value, max_value, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (p["id"], kind, f"Météo : {label} (Open-Meteo)", unit,
                                                        secrets.token_urlsafe(24), mn, mx, now_iso()))
                sn = db.execute("SELECT * FROM sensors WHERE project_id = ? AND kind = ? AND name LIKE 'Météo%'", (p["id"], kind)).fetchone()
            record_reading(db, sn, float(v), day + "T12:00:00+00:00")
            n += 1
        db.commit()
    return n


# --------------------------------------------------------------------------
# Images satellite tres haute resolution (Pleiades Neo, SkySat, Vantor)
# --------------------------------------------------------------------------
IMAGERY_PROVIDERS = {"pleiades": "Airbus Pléiades Neo (30 cm)", "skysat": "Planet SkySat (50 cm)",
                     "vantor": "Vantor, anciennement Maxar (30 cm)"}
IMAGERY_STATUS = {"demandee": "Demandée", "livree": "Livrée", "annulee": "Annulée"}


@app.route("/chantiers/<int:project_id>/images-thr", methods=["POST"])
@login_required
def imagery_order(project_id):
    p = load_project(project_id, roles=("owner",))
    gate = billing_gate(_("Commander une image satellite"))
    if gate:
        return gate
    db = get_db()
    provider = request.form.get("provider")
    if provider not in IMAGERY_PROVIDERS:
        abort(400)
    if db.execute("SELECT 1 FROM imagery_orders WHERE project_id = ? AND status = 'demandee'", (project_id,)).fetchone():
        flash(_("Une demande d'image est déjà en cours pour ce chantier."), "error")
        return redirect(url_for("project", project_id=project_id, onglet="vues"))
    db.execute("INSERT INTO imagery_orders (project_id, user_id, provider, status, note, created_at) VALUES (?,?,?,?,?,?)",
               (project_id, current_user()["id"], provider, "demandee", request.form.get("note", "").strip()[:300] or None, now_iso()))
    log(project_id, L("Image très haute résolution demandée : %(v)s", v=IMAGERY_PROVIDERS[provider]))
    notify(None, admins(db, "imagery"), L("Commande d'image très haute résolution"),
           L("%(p)s : %(v)s. Commandez l'image chez le fournisseur puis déposez-la dans l'administration.", p=p["name"],
             v=IMAGERY_PROVIDERS[provider]), "/admin#images", important=True, db=db)
    db.commit()
    flash(_("Demande envoyée. L'équipe commande l'image et vous envoie un devis avant la commande ; elle apparaîtra dans les vues satellite."), "ok")
    return redirect(url_for("project", project_id=project_id, onglet="vues"))


@app.route("/admin/images-thr/<int:order_id>", methods=["POST"])
@admin_required(perm="imagery")
def imagery_deliver(order_id):
    db = get_db()
    o = db.execute("SELECT * FROM imagery_orders WHERE id = ?", (order_id,)).fetchone()
    if o is None:
        abort(404)
    p = db.execute("SELECT * FROM projects WHERE id = ?", (o["project_id"],)).fetchone()
    if request.form.get("action") == "cancel":
        db.execute("UPDATE imagery_orders SET status = 'annulee' WHERE id = ?", (order_id,))
        staff_log(db, current_user(), "imagery_cancel", order_id)
        db.commit()
        return redirect(url_for("admin", _anchor="images"))
    file = request.files.get("file")
    month = request.form.get("month") or now_iso()[:7]
    try:
        img = Image.open(io.BytesIO(file.read()))
        img.load()
    except Exception:
        flash(_("Déposez l'image reçue du fournisseur (JPEG, PNG ou GeoTIFF RVB)."), "error")
        return redirect(url_for("admin", _anchor="images"))
    change = store_sat(db, p, month, "thr", img, o["provider"])
    sat = db.execute("SELECT id FROM sat_images WHERE project_id = ? AND month = ? AND layer = 'thr'", (p["id"], month)).fetchone()
    db.execute("UPDATE imagery_orders SET status = 'livree', delivered_at = ?, sat_image_id = ? WHERE id = ?",
               (now_iso(), sat["id"] if sat else None, order_id))
    staff_log(db, current_user(), "imagery_deliver", order_id)
    log(p["id"], L("Image très haute résolution de %(month)s ajoutée (%(v)s)", month=month, v=IMAGERY_PROVIDERS[o["provider"]])
        + (L(' (%(change)s %% de changement)', change=change) if change is not None else ""), db)
    notify(p["id"], owners_of(p, db), L("Image satellite très haute résolution disponible"),
           L("L'image de %(month)s de votre chantier est arrivée.", month=month),
           f"/chantiers/{p['id']}?onglet=vues&couche=thr", important=True, db=db)
    db.commit()
    flash(_("Image livrée au propriétaire."), "ok")
    return redirect(url_for("admin", _anchor="images"))


# --------------------------------------------------------------------------
# Zones et etages : avancement par zone
# --------------------------------------------------------------------------
ZONE_KINDS = {"batiment": "Bâtiment", "etage": "Étage", "zone": "Zone"}


def project_zones(db, project_id):
    """Zones dans l'ordre d'affichage, avec leur profondeur (batiment > etage > zone)."""
    rows = db.execute("SELECT * FROM zones WHERE project_id = ? ORDER BY position, id", (project_id,)).fetchall()
    kids = {}
    for z in rows:
        kids.setdefault(z["parent_id"], []).append(z)
    out = []

    def walk(parent, depth):
        for z in kids.get(parent, []):
            out.append((z, depth))
            walk(z["id"], depth + 1)
    walk(None, 0)
    return out


def zone_label(z, by_id):
    parts = [z["name"]]
    while z["parent_id"] and z["parent_id"] in by_id:
        z = by_id[z["parent_id"]]
        parts.insert(0, z["name"])
    return " › ".join(parts)


def zones_progress(db, project_id):
    """Pour chaque zone : quantites prevues / validees / declarees, preuves, derniere visite 360."""
    zones = project_zones(db, project_id)
    by_id = {z["id"]: z for z, _d in zones}
    items = db.execute("SELECT i.*, COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'valide'), 0) "
                       "AS done, COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'declare'), 0) "
                       "AS pending FROM work_items i WHERE i.project_id = ? ORDER BY i.id", (project_id,)).fetchall()
    out = []
    for z, depth in zones:
        zi = [i for i in items if i["zone_id"] == z["id"]]
        pct = round(sum(min(1.0, i["done"] / i["qty_planned"]) for i in zi if i["qty_planned"]) * 100 / len(zi)) if zi else None
        last_proof = db.execute("SELECT MAX(created_at) FROM proofs WHERE zone_id = ? AND ok = 1", (z["id"],)).fetchone()[0]
        last_pano = db.execute("SELECT MAX(created_at) FROM pano_visits WHERE zone_id = ? AND ok = 1", (z["id"],)).fetchone()[0]
        out.append({"z": z, "depth": depth, "label": zone_label(z, by_id), "items": zi, "pct": pct,
                    "pending": sum(1 for i in zi if i["pending"]), "proofs": db.execute(
                        "SELECT COUNT(*) FROM proofs WHERE zone_id = ? AND ok = 1", (z["id"],)).fetchone()[0],
                    "last_proof": last_proof, "last_pano": last_pano})
    return out


@app.route("/chantiers/<int:project_id>/zones", methods=["GET", "POST"])
@login_required
def zones_page(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    back = redirect(url_for("zones_page", project_id=project_id))
    if request.method == "POST":
        if role not in ("owner", "chef"):
            abort(403)
        f = request.form
        action = f.get("action")
        if action == "add":
            name = f.get("name", "").strip()[:80]
            kind = f.get("kind") if f.get("kind") in ZONE_KINDS else "zone"
            parent = to_int(f.get("parent_id"), None)
            if parent and not db.execute("SELECT 1 FROM zones WHERE id = ? AND project_id = ?", (parent, project_id)).fetchone():
                abort(400)
            if not name:
                flash(_("Nommez la zone."), "error")
                return back
            pos = (db.execute("SELECT MAX(position) FROM zones WHERE project_id = ?", (project_id,)).fetchone()[0] or 0) + 1
            db.execute("INSERT INTO zones (project_id, parent_id, name, kind, storey, position, created_at) VALUES (?,?,?,?,?,?,?)",
                       (project_id, parent, name, kind, f.get("storey") or None, pos, now_iso()))
            db.commit()
            return back
        if action == "from_bim":
            m = db.execute("SELECT * FROM bim_models WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
            if m is None:
                flash(_("Ajoutez d'abord une maquette IFC."), "error")
                return back
            existing = {r["storey"] for r in db.execute("SELECT storey FROM zones WHERE project_id = ? AND storey IS NOT NULL",
                                                         (project_id,))}
            pos = db.execute("SELECT COALESCE(MAX(position), 0) FROM zones WHERE project_id = ?", (project_id,)).fetchone()[0]
            n = 0
            for stry in json.loads(m["summary"])["storeys"]:
                if stry["name"] in existing:
                    continue
                pos += 1
                db.execute("INSERT INTO zones (project_id, name, kind, storey, position, created_at) VALUES (?,?,?,?,?,?)",
                           (project_id, stry["name"], "etage", stry["name"], pos, now_iso()))
                n += 1
            log(project_id, L("%(n)s zone(s) créée(s) depuis la maquette", n=n))
            db.commit()
            flash(_("%(n)s étage(s) créé(s) depuis la maquette.", n=n), "ok")
            return back
        z = db.execute("SELECT * FROM zones WHERE id = ? AND project_id = ?", (to_int(f.get("zone_id")), project_id)).fetchone()
        if z is None:
            abort(404)
        if action == "rename" and f.get("name", "").strip():
            db.execute("UPDATE zones SET name = ? WHERE id = ?", (f["name"].strip()[:80], z["id"]))
        elif action == "delete":
            db.execute("UPDATE proofs SET zone_id = NULL WHERE zone_id = ?", (z["id"],))
            db.execute("DELETE FROM zones WHERE id = ?", (z["id"],))
        db.commit()
        return back
    has_bim = bool(db.execute("SELECT 1 FROM bim_models WHERE project_id = ?", (project_id,)).fetchone())
    return render_template("zones.html", p=p, role=role, rows=zones_progress(db, project_id), has_bim=has_bim,
                           ZONE_KINDS=tr(ZONE_KINDS))


# --------------------------------------------------------------------------
# Visites en photos 360 degres
# --------------------------------------------------------------------------
PANO_DIR = os.path.join(UPLOAD_DIR, "360")
os.makedirs(PANO_DIR, exist_ok=True)
PANO_MAX = 40 * 1024 * 1024


@app.route("/chantiers/<int:project_id>/visites-360", methods=["GET", "POST"])
@login_required
def panos(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    zones = project_zones(db, project_id)
    by_id = {z["id"]: z for z, _d in zones}
    if request.method == "POST":
        if role not in ("owner", "chef", "inspecteur") and not member_can("capteurs"):
            abort(403)
        zid = to_int(request.form.get("zone_id"), None)
        if zid and zid not in by_id:
            abort(400)
        file = request.files.get("file")
        if not file or not file.filename or ext_of(file.filename) not in ("jpg", "jpeg", "png", "webp"):
            flash(_("Choisissez une photo 360° (JPEG équirectangulaire, comme la produisent Insta360, Ricoh Theta ou un téléphone en mode panorama 360)."), "error")
            return redirect(url_for("panos", project_id=project_id))
        raw = file.read(PANO_MAX + 1)
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            flash(_("Image illisible."), "error")
            return redirect(url_for("panos", project_id=project_id))
        reasons = []
        w, h = img.size
        if abs(w / h - 2) > 0.08 or w < 2000:
            reasons.append(L("Ce n'est pas une photo 360° : il faut une image deux fois plus large que haute, d'au moins 2 000 pixels"))
        sha = hashlib.sha256(raw).hexdigest()
        if db.execute("SELECT 1 FROM pano_visits WHERE project_id = ? AND sha256 = ?", (project_id, sha)).fetchone():
            reasons.append(L("Cette photo 360° a déjà été envoyée"))
        lat, lng, taken = read_exif(img)
        dist = None
        if lat is None:
            reasons.append(L("Pas de position GPS dans la photo : activez la localisation de la caméra 360°"))
        else:
            dist, limit, by_parcel = site_distance(p, lat, lng)
            if dist > limit:
                reasons.append(L('Prise à %(distance)s m du terrain (limite %(radius)s m)', distance=dist, radius=limit))
        if taken is not None and (datetime.now(timezone.utc) - taken.replace(tzinfo=taken.tzinfo or timezone.utc)).days > 3:
            reasons.append(L("Photo prise il y a plus de 3 jours"))
        feat = VISION.features(img)
        refs = [json.loads(r["feat"]) for r in db.execute("SELECT feat FROM pano_visits WHERE project_id = ? AND ok = 1 AND feat IS NOT NULL",
                                                          (project_id,))]
        if refs:
            d_, _s = VISION.compare(feat, refs)
            if d_ is not None and d_ <= 1:
                reasons.append(L("Presque identique à une visite 360° déjà envoyée"))
        ok = not reasons
        name = save_image(img, PANO_DIR, 6000, prefix="pano_")
        thumb = save_image(img, PANO_DIR, 800, prefix="th_")
        prev = db.execute("SELECT * FROM pano_visits WHERE project_id = ? AND ok = 1 AND " + ("zone_id = ?" if zid else "zone_id IS NULL")
                          + " ORDER BY id DESC LIMIT 1", (project_id, zid) if zid else (project_id,)).fetchone()
        change = ai_note = None
        if ok and prev:
            with Image.open(os.path.join(PANO_DIR, prev["filename"])) as before:
                change = round(VISION.change_ratio(before.resize((1024, 512)), img.resize((1024, 512))) * 100, 1)
                if VISION.ai_enabled():
                    try:
                        ai_note = json.dumps(VISION.compare_panos(before, img, zone_label(by_id[zid], by_id) if zid else p["name"]),
                                             ensure_ascii=False)
                    except Exception:
                        ai_note = None
        db.execute("INSERT INTO pano_visits (project_id, zone_id, user_id, filename, thumb, sha256, feat, lat, lng, distance, taken, ok, "
                   "reasons, change_pct, ai_note, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (project_id, zid, current_user()["id"], name, thumb, sha, json.dumps(feat), lat, lng, dist,
                    taken.isoformat() if taken else None, int(ok), I18N.store_list(reasons) if reasons else None, change, ai_note,
                    request.form.get("note", "").strip()[:300] or None, now_iso()))
        zl = zone_label(by_id[zid], by_id) if zid else _("chantier entier")
        if ok:
            log(project_id, L("Visite 360° de « %(z)s »", z=zl) + (L(" : %(c)s %% de changement depuis la précédente", c=change)
                                                                   if change is not None else ""))
            if role != "owner":
                notify(project_id, owners_of(p), L("Nouvelle visite 360°"), L("« %(z)s » : faites le tour de la zone depuis chez vous.", z=zl),
                       url_for("panos", project_id=project_id, zone=zid or ""), db=db)
            flash(_("Visite 360° enregistrée."), "ok")
        else:
            log(project_id, L("Visite 360° refusée (« %(z)s »)", z=zl))
            flash(_("Visite 360° refusée : ") + "; ".join(map(I18N.render, reasons)), "error")
        db.commit()
        return redirect(url_for("panos", project_id=project_id, zone=zid or ""))
    zfilter = to_int(request.args.get("zone"), None)
    q = "SELECT v.*, u.name AS author FROM pano_visits v JOIN users u ON u.id = v.user_id WHERE v.project_id = ?"
    args = [project_id]
    if zfilter:
        q += " AND v.zone_id = ?"
        args.append(zfilter)
    visits = db.execute(q + " ORDER BY v.id DESC", args).fetchall()
    ok_visits = [v for v in visits if v["ok"]]
    a = next((v for v in ok_visits if v["id"] == to_int(request.args.get("a"), None)), None)
    b = next((v for v in ok_visits if v["id"] == to_int(request.args.get("b"), None)), None)
    if not b and ok_visits:
        b = ok_visits[0]
    if not a and b:
        a = next((v for v in ok_visits if v["id"] != b["id"] and v["zone_id"] == b["zone_id"]), None)
    return render_template("panos.html", p=p, role=role, zones=zones, by_id=by_id, zfilter=zfilter, visits=visits,
                           ok_visits=ok_visits, a=a, b=b, ai_b=json.loads(b["ai_note"]) if b and b["ai_note"] else None,
                           zone_label=zone_label, can_upload=role in ("owner", "chef", "inspecteur") or member_can("capteurs"))


@app.route("/visites-360/<int:vid>/<kind>")
@login_required
def pano_file(vid, kind):
    v = get_db().execute("SELECT * FROM pano_visits WHERE id = ?", (vid,)).fetchone()
    if v is None or kind not in ("image", "vignette"):
        abort(404)
    load_project(v["project_id"], roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    return send_from_directory(PANO_DIR, v["filename"] if kind == "image" else v["thumb"])


# --------------------------------------------------------------------------
# Quantites installees et rapport d'avancement physique
# --------------------------------------------------------------------------
QTY_UNITS = ["m²", "m³", "ml", "u", "kg", "%"]


def bim_items_for_zone(summary, storey):
    for s_ in summary["storeys"]:
        if s_["name"] == storey:
            return s_["counts"]
    return {}


@app.route("/chantiers/<int:project_id>/quantites", methods=["GET", "POST"])
@login_required
def quantities(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    me = current_user()
    back = redirect(url_for("quantities", project_id=project_id))
    zones = project_zones(db, project_id)
    by_id = {z["id"]: z for z, _d in zones}
    is_chef = role == "chef" or (role == "intervenant" and g.get("member_role") == "conducteur")
    can_validate = role in ("owner", "inspecteur")
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "add":
            if role != "owner" and not is_chef:
                abort(403)
            zid, sid = to_int(f.get("zone_id"), None), to_int(f.get("step_id"), None)
            if (zid and zid not in by_id) or (sid and not db.execute("SELECT 1 FROM steps WHERE id = ? AND project_id = ?",
                                                                     (sid, project_id)).fetchone()):
                abort(400)
            q = to_float(f.get("qty_planned"))
            label = f.get("label", "").strip()[:120]
            if not label or not q or q <= 0 or f.get("unit") not in QTY_UNITS:
                flash(_("Indiquez l'ouvrage, l'unité et la quantité prévue."), "error")
                return back
            db.execute("INSERT INTO work_items (project_id, zone_id, step_id, label, unit, qty_planned, source, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (project_id, zid, sid, label, f["unit"], q, "manuel", now_iso()))
            db.commit()
            return back
        if action == "from_bim":
            if role != "owner":
                abort(403)
            m = db.execute("SELECT * FROM bim_models WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
            if m is None:
                flash(_("Ajoutez d'abord une maquette IFC."), "error")
                return back
            summary = json.loads(m["summary"])
            links = {r["storey"]: r["step_id"] for r in db.execute("SELECT * FROM bim_storeys WHERE project_id = ?", (project_id,))}
            n = 0
            for z, _d in zones:
                if not z["storey"]:
                    continue
                for label, count in bim_items_for_zone(summary, z["storey"]).items():
                    if db.execute("SELECT 1 FROM work_items WHERE zone_id = ? AND label = ? AND source = 'bim'", (z["id"], label)).fetchone():
                        db.execute("UPDATE work_items SET qty_planned = ? WHERE zone_id = ? AND label = ? AND source = 'bim'",
                                   (count, z["id"], label))
                        continue
                    db.execute("INSERT INTO work_items (project_id, zone_id, step_id, label, unit, qty_planned, source, created_at) "
                               "VALUES (?,?,?,?,?,?,?,?)", (project_id, z["id"], links.get(z["storey"]), label, "u", count, "bim", now_iso()))
                    n += 1
            log(project_id, L("%(n)s ouvrage(s) prévu(s) importé(s) de la maquette version %(v)s", n=n, v=m["version"]))
            db.commit()
            flash(_("%(n)s ouvrage(s) importé(s) de la maquette.", n=n), "ok")
            return back
        item = db.execute("SELECT * FROM work_items WHERE id = ? AND project_id = ?", (to_int(f.get("item_id")), project_id)).fetchone()
        if action == "declare":
            if not is_chef or item is None:
                abort(403)
            q = to_float(f.get("qty"))
            proof_id = to_int(f.get("proof_id"), None)
            if not q or q <= 0:
                flash(_("Indiquez la quantité posée."), "error")
                return back
            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
            pr = db.execute("SELECT * FROM proofs WHERE id = ? AND project_id = ? AND ok = 1 AND created_at > ?",
                            (proof_id, project_id, since)).fetchone() if proof_id else None
            if pr is None:
                flash(_("Choisissez une photo vérifiée de moins de 7 jours qui montre l'ouvrage posé."), "error")
                return back
            db.execute("INSERT INTO work_progress (item_id, qty, proof_id, note, status, user_id, created_at) VALUES (?,?,?,?,?,?,?)",
                       (item["id"], q, pr["id"], f.get("note", "").strip()[:300] or None, "declare", me["id"], now_iso()))
            log(project_id, L("Quantité posée déclarée : %(q)s %(u)s de %(l)s", q=fmt_qty(q), u=item["unit"], l=item["label"]), db, me["id"])
            notify(project_id, owners_of(p, db) + controllers_of(db, p), L("Quantité posée à valider"),
                   L("%(q)s %(u)s de %(l)s, avec photo.", q=fmt_qty(q), u=item["unit"], l=item["label"]),
                   url_for("quantities", project_id=project_id), db=db)
            db.commit()
            flash(_("Quantité déclarée. Elle sera comptée une fois validée."), "ok")
            return back
        if action in ("validate", "refuse"):
            if not can_validate:
                abort(403)
            w = db.execute("SELECT w.* FROM work_progress w JOIN work_items i ON i.id = w.item_id WHERE w.id = ? AND i.project_id = ? "
                           "AND w.status = 'declare'", (to_int(f.get("progress_id")), project_id)).fetchone()
            if w is None:
                abort(404)
            it = db.execute("SELECT * FROM work_items WHERE id = ?", (w["item_id"],)).fetchone()
            db.execute("UPDATE work_progress SET status = ?, validated_by = ?, validated_at = ? WHERE id = ?",
                       ("valide" if action == "validate" else "refuse", me["id"], now_iso(), w["id"]))
            if action == "validate":
                emit_event(db, project_id, "quantite.validee", {"ouvrage": it["label"], "quantite": w["qty"], "unite": it["unit"],
                                                                "zone_id": it["zone_id"], "etape_id": it["step_id"]})
            msg = (L("Quantité validée : %(q)s %(u)s de %(l)s", q=fmt_qty(w["qty"]), u=it["unit"], l=it["label"]) if action == "validate"
                   else L("Quantité refusée : %(q)s %(u)s de %(l)s", q=fmt_qty(w["qty"]), u=it["unit"], l=it["label"]))
            log(project_id, msg, db, me["id"])
            db.commit()
            return back
        if action == "delete" and role == "owner" and item is not None:
            db.execute("DELETE FROM work_items WHERE id = ?", (item["id"],))
            db.commit()
            return back
        abort(400)
    rows = zones_progress(db, project_id)
    unzoned = db.execute("SELECT i.*, COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'valide'), 0) "
                         "AS done, COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'declare'), 0) "
                         "AS pending FROM work_items i WHERE i.project_id = ? AND i.zone_id IS NULL", (project_id,)).fetchall()
    pending = db.execute("SELECT w.*, i.label, i.unit, i.zone_id, u.name AS author FROM work_progress w JOIN work_items i ON i.id = w.item_id "
                         "JOIN users u ON u.id = w.user_id WHERE i.project_id = ? AND w.status = 'declare' ORDER BY w.id",
                         (project_id,)).fetchall()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    recent_proofs = db.execute("SELECT id, note, created_at, zone_id FROM proofs WHERE project_id = ? AND ok = 1 AND created_at > ? "
                               "ORDER BY id DESC LIMIT 40", (project_id, since)).fetchall() if is_chef else []
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    return render_template("quantities.html", p=p, role=role, rows=rows, unzoned=unzoned, pending=pending, zones=zones, by_id=by_id,
                           zone_label=zone_label, steps=steps, units=QTY_UNITS, is_chef=is_chef, can_validate=can_validate,
                           recent_proofs=recent_proofs,
                           has_bim=bool(db.execute("SELECT 1 FROM bim_models WHERE project_id = ?", (project_id,)).fetchone()))


def physical_report_rows(db, project_id):
    rows = []
    zones = project_zones(db, project_id)
    by_id = {z["id"]: z for z, _d in zones}
    for i in db.execute("SELECT i.*, st.name AS step_name, "
                        "COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'valide'), 0) AS done, "
                        "COALESCE((SELECT SUM(qty) FROM work_progress w WHERE w.item_id = i.id AND w.status = 'declare'), 0) AS pending "
                        "FROM work_items i LEFT JOIN steps st ON st.id = i.step_id WHERE i.project_id = ? ORDER BY i.zone_id, i.id",
                        (project_id,)):
        rows.append({"zone": zone_label(by_id[i["zone_id"]], by_id) if i["zone_id"] in by_id else "", "step": i["step_name"] or "",
                     "label": i["label"], "unit": i["unit"], "planned": i["qty_planned"], "done": i["done"], "pending": i["pending"],
                     "pct": round(min(1.0, i["done"] / i["qty_planned"]) * 100) if i["qty_planned"] else 0})
    return rows


@app.route("/chantiers/<int:project_id>/avancement-physique")
@app.route("/chantiers/<int:project_id>/avancement-physique.<fmt>")
@login_required
def physical_report(project_id, fmt="html"):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    db = get_db()
    rows = physical_report_rows(db, project_id)
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow([_("Zone"), _("Étape"), _("Ouvrage"), _("Unité"), _("Prévu"), _("Posé et validé"), _("Déclaré, à valider"), _("Avancement (%)")])
        for r in rows:
            w.writerow([r["zone"], r["step"], r["label"], r["unit"], fmt_qty(r["planned"]), fmt_qty(r["done"]), fmt_qty(r["pending"]), r["pct"]])
        resp = app.response_class("﻿" + out.getvalue(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f'attachment; filename="chantier-{project_id}-avancement-physique.csv"'
        return resp
    if fmt != "html":
        abort(404)
    s = project_stats(project_id)
    overall = round(sum(r["pct"] for r in rows) / len(rows)) if rows else None
    return render_template("physical_report.html", p=p, rows=rows, s=s, overall=overall, today=now_iso(),
                           zones=zones_progress(db, project_id), pred=project_prediction(p, s))


# --------------------------------------------------------------------------
# API ouverte : cles par chantier, webhooks signes
# --------------------------------------------------------------------------
def emit_event(db, project_id, event, data):
    """Met en file un evenement pour les webhooks abonnes ; l'envoi se fait apres la reponse."""
    try:
        hooks = db.execute("SELECT * FROM webhooks WHERE active = 1 AND (project_id = ? OR (project_id IS NULL AND user_id IN "
                           "(SELECT owner_id FROM projects WHERE id = ? UNION SELECT user_id FROM project_members WHERE project_id = ? "
                           "AND role IN ('coproprio', 'finance'))))", (project_id, project_id, project_id)).fetchall()
    except Exception:
        return
    ids = []
    for h in hooks:
        if event not in h["events"].split(","):
            continue
        payload = json.dumps({"event": event, "chantier_id": project_id, "date": now_iso(), "data": data}, ensure_ascii=False,
                             default=str)
        ids.append(db.execute("INSERT INTO webhook_deliveries (webhook_id, event, payload, created_at, next_at) VALUES (?,?,?,?,?)",
                              (h["id"], event, payload, now_iso(), now_iso())).lastrowid)
    if ids and has_request_context():
        g.setdefault("pending_hooks", []).extend(ids)


@app.after_request
def dispatch_hooks(resp):
    ids = g.pop("pending_hooks", None)
    if ids and resp.status_code < 500:
        run_async(deliver_webhooks, ids)
    return resp


def deliver_webhooks(ids=None):
    """Envoie les webhooks en attente (ceux donnes, ou ceux dont l'heure de relance est passee)."""
    db = connect()
    try:
        if ids:
            rows = db.execute("SELECT * FROM webhook_deliveries WHERE id IN (%s) AND status = 'en_attente'" % ",".join("?" * len(ids)),
                              ids).fetchall()
        else:
            rows = db.execute("SELECT * FROM webhook_deliveries WHERE status = 'en_attente' AND next_at <= ?", (now_iso(),)).fetchall()
        n = 0
        for d_ in rows:
            h = db.execute("SELECT * FROM webhooks WHERE id = ?", (d_["webhook_id"],)).fetchone()
            if h is None or not h["active"]:
                db.execute("UPDATE webhook_deliveries SET status = 'annule' WHERE id = ?", (d_["id"],))
                continue
            body = d_["payload"].encode()
            ts = str(int(datetime.now(timezone.utc).timestamp()))
            code = HOOKS.send(h["url"], body, {"X-ChantierVrai-Event": d_["event"], "X-ChantierVrai-Delivery": str(d_["id"]),
                                               "X-ChantierVrai-Timestamp": ts,
                                               "X-ChantierVrai-Signature": HOOKS.signature(h["secret"], ts, body)})
            attempts = d_["attempts"] + 1
            if 200 <= code < 300:
                db.execute("UPDATE webhook_deliveries SET status = 'livre', attempts = ?, response_code = ? WHERE id = ?",
                           (attempts, code, d_["id"]))
                db.execute("UPDATE webhooks SET failures = 0 WHERE id = ?", (h["id"],))
                n += 1
            else:
                done = attempts >= len(HOOKS.BACKOFF_MIN)
                nxt = (datetime.now(timezone.utc) + timedelta(minutes=HOOKS.BACKOFF_MIN[min(attempts, len(HOOKS.BACKOFF_MIN)) - 1]))
                db.execute("UPDATE webhook_deliveries SET status = ?, attempts = ?, response_code = ?, next_at = ? WHERE id = ?",
                           ("echec" if done else "en_attente", attempts, code, nxt.isoformat(timespec="seconds"), d_["id"]))
                fails = h["failures"] + 1
                db.execute("UPDATE webhooks SET failures = ?, active = ? WHERE id = ?", (fails, 0 if fails >= 30 else 1, h["id"]))
        db.commit()
        return n
    finally:
        db.close()


def ext_projects(db, key):
    u = db.execute("SELECT * FROM users WHERE id = ?", (key["user_id"],)).fetchone()
    owned = db.execute("SELECT * FROM projects WHERE owner_id = ? OR id IN (SELECT project_id FROM project_members WHERE user_id = ? "
                       "AND role IN ('coproprio', 'finance')) ORDER BY id", (u["id"], u["id"])).fetchall()
    return [p for p in owned if key["project_id"] is None or p["id"] == key["project_id"]]


def ext_auth(scope="read"):
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            raw = auth[7:].strip() if auth.startswith("Bearer ") else request.headers.get("X-Api-Key", "")
            if not raw.startswith("cvk_"):
                return jsonify(ok=False, error="missing_api_key"), 401
            db = get_db()
            key = db.execute("SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
                             (hashlib.sha256(raw.encode()).hexdigest(),)).fetchone()
            u = db.execute("SELECT * FROM users WHERE id = ?", (key["user_id"],)).fetchone() if key else None
            if key is None or u is None or u["blocked"] or u["deleted"]:
                return jsonify(ok=False, error="invalid_api_key"), 401
            if scope == "write" and key["scope"] != "write":
                return jsonify(ok=False, error="read_only_key"), 403
            if not key["last_used_at"] or key["last_used_at"][:13] != now_iso()[:13]:
                db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now_iso(), key["id"]))
                db.commit()
            g.ext_key = key
            g.user = u
            if "project_id" in kwargs:
                p = next((x for x in ext_projects(db, key) if x["id"] == kwargs["project_id"]), None)
                if p is None:
                    return jsonify(ok=False, error="project_not_found"), 404
                g.ext_project = p
            return view(*args, **kwargs)
        return wrapped
    return deco


def ext_project_json(db, p):
    s = project_stats(p["id"], db)
    pred = project_prediction(p, s, db)
    t = project_trust(p, s, pred, db)
    return {"id": p["id"], "nom": p["name"], "adresse": p["address"], "lat": p["lat"], "lng": p["lng"], "type": p["building_type"],
            "niveaux": p["levels"], "montant_total": s["total"], "paye": s["paid"], "avancement_verifie_pct": s["verified_pct"],
            "avancement_declare_pct": s["declared_pct"], "debut": p["start_date"],
            "fin_prevue": str(pred["planned_end"]) if pred else None, "fin_estimee": str(pred["predicted_end"]) if pred else None,
            "retard_jours": pred["delay"] if pred else None, "indice_confiance": t["score"],
            "derniere_preuve_jours": s["days_silent"]}


@app.route("/api/ext/v1/chantiers")
@ext_auth()
def ext_list():
    db = get_db()
    return jsonify(ok=True, chantiers=[ext_project_json(db, p) for p in ext_projects(db, g.ext_key)])


@app.route("/api/ext/v1/chantiers/<int:project_id>")
@ext_auth()
def ext_project(project_id):
    return jsonify(ok=True, chantier=ext_project_json(get_db(), g.ext_project))


@app.route("/api/ext/v1/chantiers/<int:project_id>/etapes")
@ext_auth()
def ext_steps(project_id):
    db = get_db()
    out = []
    for st in db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)):
        checks = step_checks(db, st["id"])
        out.append({"id": st["id"], "nom": st["name"], "montant": st["amount"], "statut": st["status"], "declaree_le": st["declared_at"],
                    "payee_le": st["paid_at"], "reference_paiement": st["pay_ref"], "duree_prevue_jours": st["planned_days"],
                    "controles": [{"nom": I18N.render(c["name"]), "obligatoire": bool(c["required"]), "statut": c["status"],
                                   "valeur": c["value"], "unite": c["unit"], "le": c["checked_at"]} for c in checks]})
    return jsonify(ok=True, etapes=out)


@app.route("/api/ext/v1/chantiers/<int:project_id>/preuves")
@ext_auth()
def ext_proofs(project_id):
    since = request.args.get("depuis") or "0000"
    rows = get_db().execute("SELECT id, step_id, zone_id, kind, source, ok, photo_lat, photo_lng, distance, photo_taken, created_at, note, ai_step, "
                            "ai_conf FROM proofs WHERE project_id = ? AND created_at > ? ORDER BY id LIMIT 500", (project_id, since)).fetchall()
    return jsonify(ok=True, preuves=[dict(r) | {"photo_url": public_url(url_for("proof_photo", proof_id=r["id"]))} for r in rows])


@app.route("/api/ext/v1/chantiers/<int:project_id>/paiements")
@ext_auth()
def ext_payments(project_id):
    """Mouvements du sequestre (s'il y en a) et paiements suivis : bons a payer, declarations, confirmations."""
    db = get_db()
    rows = db.execute("SELECT t.id, t.kind, t.amount, t.status, t.ref, t.provider, t.provider_ref, t.step_id, t.order_id, t.created_at "
                      "FROM transactions t WHERE t.project_id = ? ORDER BY t.id", (project_id,)).fetchall()
    bons = []
    for d in project_payments(db, g.ext_project):
        bons.append({"bon_a_payer": d["ref"], "objet": d["kind"], "objet_id": d["ref_id"], "libelle": I18N.render(d["label"]),
                     "beneficiaire_id": d["payee_id"], "montant_du": d["amount"], "confirme": d["confirmed"],
                     "declare": d["declared"], "paye": d["done"],
                     "paiements": [{"id": r["id"], "montant": r["amount"], "moyen": r["method"], "reference": r["reference"],
                                    "date": r["paid_on"], "statut": r["status"], "recu_sha256": r["receipt_sha"],
                                    "motif_contestation": r["contest_note"], "declare_le": r["created_at"],
                                    "repondu_le": r["answered_at"]} for r in d["records"]]})
    return jsonify(ok=True, paiements=[dict(r) for r in rows], paiements_suivis=bons)


@app.route("/api/ext/v1/chantiers/<int:project_id>/stock")
@ext_auth()
def ext_stock(project_id):
    table, alerts = stock_summary(get_db(), project_id)
    return jsonify(ok=True, stock=[{k: r[k] for k in ("material", "unit", "planned", "bought", "delivered", "used", "lost", "available")}
                                   for r in table], alertes=alerts)


@app.route("/api/ext/v1/chantiers/<int:project_id>/avancement")
@ext_auth()
def ext_progress(project_id):
    db = get_db()
    zones = [{"id": r["z"]["id"], "nom": r["label"], "type": r["z"]["kind"], "avancement_pct": r["pct"], "preuves": r["proofs"],
              "derniere_preuve": r["last_proof"], "derniere_visite_360": r["last_pano"]} for r in zones_progress(db, project_id)]
    return jsonify(ok=True, zones=zones, quantites=physical_report_rows(db, project_id))


@app.route("/api/ext/v1/chantiers/<int:project_id>/anomalies")
@ext_auth()
def ext_anomalies(project_id):
    db = get_db()
    p = g.ext_project
    s = project_stats(project_id, db)
    alerts = [{"titre": a[0], "detail": a[2] if len(a) > 2 else None} for a in project_alerts(p, s, project_prediction(p, s, db))]
    return jsonify(ok=True, anomalies=alerts)


@app.route("/api/ext/v1/chantiers/<int:project_id>/quantites-prevues", methods=["POST"])
@ext_auth("write")
def ext_add_items(project_id):
    """Importe des quantites prevues depuis un devis ou un logiciel de metre : [{"ouvrage", "unite", "quantite", "zone", "etape_id"}]."""
    db = get_db()
    data = request.get_json(silent=True) or {}
    items = data.get("quantites") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return jsonify(ok=False, error="quantites_required"), 400
    zones = {z["name"]: z["id"] for z, _d in project_zones(db, project_id)}
    steps = {r["id"] for r in db.execute("SELECT id FROM steps WHERE project_id = ?", (project_id,))}
    created, errors = 0, []
    for i, it in enumerate(items[:500]):
        try:
            label, unit, q = str(it["ouvrage"]).strip()[:120], str(it["unite"]), float(it["quantite"])
        except (KeyError, TypeError, ValueError):
            errors.append({"ligne": i, "erreur": "ouvrage, unite et quantite obligatoires"})
            continue
        if not label or unit not in QTY_UNITS or not (q > 0 and math.isfinite(q)):
            errors.append({"ligne": i, "erreur": f"unite parmi {QTY_UNITS}, quantite positive"})
            continue
        zid = zones.get(it.get("zone")) if it.get("zone") else None
        sid = it.get("etape_id") if it.get("etape_id") in steps else None
        db.execute("INSERT INTO work_items (project_id, zone_id, step_id, label, unit, qty_planned, source, created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (project_id, zid, sid, label, unit, q, "api", now_iso()))
        created += 1
    if created:
        log(project_id, L("%(n)s quantité(s) prévue(s) importée(s) par l'API (%(k)s)", n=created, k=g.ext_key["name"]), db,
            g.ext_key["user_id"])
    db.commit()
    return jsonify(ok=not errors, crees=created, erreurs=errors), (200 if not errors else 207)


@app.route("/compte/api", methods=["GET", "POST"])
@login_required
def api_settings():
    me = current_user()
    if me["role"] != "proprio":
        abort(403)
    db = get_db()
    projects = [p for p in user_projects(me) if project_role(p) == "owner"]
    pids = {p["id"] for p in projects}
    new_key = new_secret = None
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        pid = to_int(f.get("project_id"), None)
        if pid and pid not in pids:
            abort(403)
        if action == "key":
            gate = billing_gate(_("Créer une clé d'API"))
            if gate:
                return gate
            raw = "cvk_" + secrets.token_urlsafe(32)
            db.execute("INSERT INTO api_keys (user_id, project_id, name, prefix, key_hash, scope, created_at) VALUES (?,?,?,?,?,?,?)",
                       (me["id"], pid, f.get("name", "").strip()[:60] or _("Clé"), raw[:12],
                        hashlib.sha256(raw.encode()).hexdigest(), "write" if f.get("scope") == "write" else "read", now_iso()))
            db.commit()
            new_key = raw
        elif action == "revoke":
            db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ?", (now_iso(), to_int(f.get("key_id")), me["id"]))
            db.commit()
            return redirect(url_for("api_settings"))
        elif action == "hook":
            url = f.get("url", "").strip()[:300]
            events = [e for e in f.getlist("events") if e in HOOKS.EVENTS]
            if not HOOKS.url_ok(url) or not events:
                flash(_("Adresse https publique et au moins un événement obligatoires."), "error")
                return redirect(url_for("api_settings"))
            new_secret = "whsec_" + secrets.token_urlsafe(24)
            db.execute("INSERT INTO webhooks (user_id, project_id, url, secret, events, created_at) VALUES (?,?,?,?,?,?)",
                       (me["id"], pid, url, new_secret, ",".join(events), now_iso()))
            db.commit()
        elif action in ("hook_delete", "hook_test", "hook_toggle"):
            h = db.execute("SELECT * FROM webhooks WHERE id = ? AND user_id = ?", (to_int(f.get("hook_id")), me["id"])).fetchone()
            if h is None:
                abort(404)
            if action == "hook_delete":
                db.execute("DELETE FROM webhooks WHERE id = ?", (h["id"],))
            elif action == "hook_toggle":
                db.execute("UPDATE webhooks SET active = ?, failures = 0 WHERE id = ?", (0 if h["active"] else 1, h["id"]))
            else:
                did = db.execute("INSERT INTO webhook_deliveries (webhook_id, event, payload, created_at, next_at) VALUES (?,?,?,?,?)",
                                 (h["id"], "test", json.dumps({"event": "test", "date": now_iso(), "data": {"message": "ChantierVrai"}}),
                                  now_iso(), now_iso())).lastrowid
                g.setdefault("pending_hooks", []).append(did)
                flash(_("Événement de test envoyé."), "ok")
            db.commit()
            return redirect(url_for("api_settings"))
    keys = db.execute("SELECT k.*, p.name AS project_name FROM api_keys k LEFT JOIN projects p ON p.id = k.project_id WHERE k.user_id = ? "
                      "ORDER BY k.id DESC", (me["id"],)).fetchall()
    hooks = db.execute("SELECT h.*, p.name AS project_name FROM webhooks h LEFT JOIN projects p ON p.id = h.project_id WHERE h.user_id = ? "
                       "ORDER BY h.id DESC", (me["id"],)).fetchall()
    deliveries = db.execute("SELECT d.* FROM webhook_deliveries d JOIN webhooks h ON h.id = d.webhook_id WHERE h.user_id = ? "
                            "ORDER BY d.id DESC LIMIT 20", (me["id"],)).fetchall()
    return render_template("api_settings.html", projects=projects, keys=keys, hooks=hooks, deliveries=deliveries, new_key=new_key,
                           new_secret=new_secret, EVENTS=tr(HOOKS.EVENTS))


@app.route("/api/docs")
def api_docs():
    return render_template("api_docs.html", EVENTS=tr(HOOKS.EVENTS), base=public_url("/api/ext/v1") or request.host_url.rstrip("/") + "/api/ext/v1",
                           units=QTY_UNITS)


# --------------------------------------------------------------------------
# Assistant IA (cours relus + donnees du chantier)
# --------------------------------------------------------------------------
ASSISTANT_DAILY = 40


def project_brief(db, p):
    """Etat du chantier en quelques lignes, tel que l'application le mesure : c'est ce que l'assistant peut citer."""
    s = project_stats(p["id"], db)
    pred = project_prediction(p, s, db)
    lines = [f"Chantier : {p['name']} ({p['address'] or ''}). Montant total : {s['total']} FCFA, payé : {s['paid']} FCFA.",
             f"Avancement vérifié : {s['verified_pct']} %, déclaré : {s['declared_pct']} %."]
    if pred:
        lines.append(f"Fin prévue : {pred['planned_end']}, fin estimée : {pred['predicted_end']}, retard prévu : {pred['delay']} jours.")
    for st in s["steps"]:
        miss = db.execute("SELECT COUNT(*) FROM step_checks WHERE step_id = ? AND required = 1 AND status != 'conforme'",
                          (st["id"],)).fetchone()[0]
        lines.append(f"- Étape « {st['name']} » : {ORDER_STEP_STATUS.get(st['status'], st['status'])}, {st['amount']} FCFA"
                     + (f", {miss} contrôle(s) obligatoire(s) non faits" if miss and st["status"] not in ("paye", "versement") else ""))
    if s["days_silent"] is not None:
        lines.append(f"Dernière preuve photo il y a {s['days_silent']} jour(s) ; {s['refused']} photo(s) refusée(s) sur {s['proofs_total']}.")
    _t, alerts = stock_summary(db, p["id"])
    lines += [f"Alerte stock : {a}" for a in alerts[:5]]
    t = project_trust(p, s, pred, db)
    if t["score"] is not None:
        lines.append(f"Indice de confiance : {t['score']}/100 ; " + " ; ".join(
            f"{I18N.render(c['title'])} {c['score']} ({I18N.render(c['why'])})" for c in t["criteria"] if c["score"] is not None))
    for a in project_alerts(p, s, pred)[:6]:
        lines.append(f"Alerte : {a[0]}")
    return "\n".join(lines)


ORDER_STEP_STATUS = {"attente": "à venir", "en_cours": "en cours", "declare": "déclarée terminée, à valider",
                     "paye": "validée et payée", "versement": "paiement en cours"}


@app.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
    me = current_user()
    db = get_db()
    projects = [p for p in user_projects(me) if project_role(p) in ("owner", "chef", "inspecteur", "intervenant")]
    pid = to_int(request.values.get("chantier"), None)
    project = next((p for p in projects if p["id"] == pid), None)
    answer = None
    if request.method == "POST":
        q = request.form.get("q", "").strip()[:600]
        if len(q) < 4:
            flash(_("Posez une question un peu plus précise."), "error")
            return redirect(url_for("assistant", chantier=pid))
        passages, structural = ACAD.ask(q, g.lang, limit=5)
        if not ASSIST.enabled():
            answer = {"q": q, "text": None, "passages": passages, "structural": structural, "fallback": True}
        else:
            since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
            n = db.execute("SELECT COUNT(*) FROM assistant_messages WHERE user_id = ? AND created_at > ?",
                           (me["id"], since)).fetchone()[0]
            if n >= ASSISTANT_DAILY and not me["is_admin"]:
                flash(_("Vous avez posé %(n)s questions aujourd'hui : revenez demain.", n=ASSISTANT_DAILY), "error")
                return redirect(url_for("assistant", chantier=pid))
            recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
            hist = db.execute("SELECT question, answer FROM assistant_messages WHERE user_id = ? AND "
                              + ("project_id = ?" if project else "project_id IS NULL") + " AND created_at > ? ORDER BY id DESC LIMIT 4",
                              (me["id"], project["id"], recent) if project else (me["id"], recent)).fetchall()
            sources = ASSIST.build_sources(passages, project_brief(db, project) if project else None)
            try:
                text = ASSIST.call(q, [(h["question"], h["answer"]) for h in reversed(hist)], sources, g.lang)
            except Exception:
                answer = {"q": q, "text": None, "passages": passages, "structural": structural, "fallback": True, "error": True}
            else:
                nums, used_project = ASSIST.cited(text, len(passages))
                db.execute("INSERT INTO assistant_messages (user_id, project_id, question, answer, sources, created_at) "
                           "VALUES (?,?,?,?,?,?)", (me["id"], project["id"] if project else None, q, text,
                                                    json.dumps([passages[i - 1][1] for i in nums]), now_iso()))
                db.commit()
                answer = {"q": q, "text": text, "passages": passages, "cited": nums, "used_project": used_project,
                          "structural": structural, "fallback": False}
    history = db.execute("SELECT * FROM assistant_messages WHERE user_id = ? AND " + ("project_id = ?" if project else "project_id IS NULL")
                         + " ORDER BY id DESC LIMIT 6", (me["id"], project["id"]) if project else (me["id"],)).fetchall()
    return render_template("assistant.html", projects=projects, project=project, answer=answer,
                           history=[h for h in history if not answer or h["question"] != answer["q"]], ai=ASSIST.enabled())


# --------------------------------------------------------------------------
# Lecture des plans par IA : pieces, surfaces, murs -> calculateur et prevu
# --------------------------------------------------------------------------
PLAN_EXT = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def add_to_plan(db, project_id, st, lines):
    for mat, unit, q in lines:
        if mat == "Eau" or not q:
            continue
        row = db.execute("SELECT * FROM materials_plan WHERE step_id = ? AND material = ? AND COALESCE(unit, '') = ?",
                         (st["id"], mat, unit)).fetchone()
        if row:
            db.execute("UPDATE materials_plan SET qty_planned = COALESCE(qty_planned, 0) + ? WHERE id = ?", (q, row["id"]))
        else:
            db.execute("INSERT INTO materials_plan (project_id, step_id, material, unit, qty_planned) VALUES (?,?,?,?,?)",
                       (project_id, st["id"], mat, unit, q))


def plan_quantities(v):
    """A partir des mesures du plan (corrigees par l'utilisateur), les calculs de second oeuvre et de maconnerie."""
    h = v.get("height") or 2.8
    walls = (v.get("ext_walls") or 0) + (v.get("int_walls") or 0)
    openings = round((v.get("doors") or 0) * 1.9 + (v.get("windows") or 0) * 1.5, 1)
    wall_area = max(0.0, walls * h - openings)
    area = v.get("floor_area") or 0
    calcs = {}
    if walls:
        calcs["maconnerie"] = {"long": walls, "haut": h, "ouv": openings, "parpaing": "15", "pertes": "5"}
        calcs["enduit"] = {"surface": round(wall_area, 1), "faces": "2", "ep": "1.5", "pertes": "10"}
        calcs["peinture"] = {"surface": round(wall_area * 2 + area, 1), "couches": "2", "rend": "10", "pertes": "5"}
    if area:
        calcs["carrelage"] = {"long": area, "larg": "1", "pieces": "1", "pertes": "10"}
    return {k: {"params": prm, "result": CALC.compute(k, {k2: str(v2) for k2, v2 in prm.items()})} for k, prm in calcs.items()}


@app.route("/chantiers/<int:project_id>/lecture-plan", methods=["GET", "POST"])
@login_required
def plan_reading(project_id):
    p = load_project(project_id, roles=("owner", "chef", "intervenant"))
    if g.project_role == "intervenant" and not member_can("documents"):
        abort(403)
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    plans = db.execute("SELECT * FROM documents WHERE project_id = ? AND category = 'Plan' ORDER BY id DESC", (project_id,)).fetchall()
    back = redirect(url_for("plan_reading", project_id=project_id))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "read":
            raw, mt, doc_id = None, None, to_int(request.form.get("doc_id"), None)
            file = request.files.get("file")
            if file and file.filename:
                ext = ext_of(file.filename)
                if ext not in PLAN_EXT:
                    flash(_("Envoyez le plan en PDF ou en image (JPEG, PNG)."), "error")
                    return back
                raw, mt = file.read(20 * 1024 * 1024), PLAN_EXT[ext]
            elif doc_id:
                doc = next((d_ for d_ in plans if d_["id"] == doc_id), None)
                if doc is None:
                    abort(404)
                ext = ext_of(doc["original_name"] or doc["filename"])
                if ext not in PLAN_EXT:
                    flash(_("Ce document n'est ni un PDF ni une image."), "error")
                    return back
                with open(os.path.join(DOC_DIR, doc["filename"]), "rb") as fh:
                    raw, mt = fh.read(), PLAN_EXT[ext]
            else:
                flash(_("Choisissez un plan."), "error")
                return back
            if not VISION.ai_enabled():
                flash(_("La lecture automatique n'est pas activée sur ce serveur : saisissez les mesures du plan ci-dessous."), "error")
                return back
            try:
                result = VISION.read_plan(raw, mt)
            except Exception:
                flash(_("Le plan n'a pas pu être lu. Essayez une image plus nette, ou saisissez les mesures."), "error")
                return back
            db.execute("INSERT INTO plan_readings (project_id, user_id, doc_id, result, created_at) VALUES (?,?,?,?,?)",
                       (project_id, current_user()["id"], doc_id, json.dumps(result, ensure_ascii=False), now_iso()))
            log(project_id, L("Plan lu par l'IA : %(a)s m², %(n)s pièce(s)", a=fmt_qty(result["floor_area"] or 0), n=len(result["rooms"])))
            db.commit()
            flash(_("Plan lu. Vérifiez chaque valeur avec les cotes du plan avant de vous en servir."), "ok")
            return back
        if action == "save":
            f = request.form
            result = {"floor_area": to_float(f.get("floor_area")), "ext_walls": to_float(f.get("ext_walls")),
                      "int_walls": to_float(f.get("int_walls")), "height": to_float(f.get("height")),
                      "doors": to_int(f.get("doors"), 0), "windows": to_int(f.get("windows"), 0), "rooms": [],
                      "levels": 1, "scale": None, "confidence": None, "remarks": "", "source": "manuel"}
            last = db.execute("SELECT * FROM plan_readings WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
            if last:
                prev = json.loads(last["result"])
                result.update({k: prev.get(k) for k in ("rooms", "levels", "scale", "confidence", "remarks")})
                result["source"] = "corrige" if prev.get("source") != "manuel" else "manuel"
            db.execute("INSERT INTO plan_readings (project_id, user_id, doc_id, result, created_at) VALUES (?,?,?,?,?)",
                       (project_id, current_user()["id"], last["doc_id"] if last else None, json.dumps(result, ensure_ascii=False), now_iso()))
            if g.project_role == "owner" and result["floor_area"] and not p["surface_floor"] and f.get("update_sheet"):
                db.execute("UPDATE projects SET surface_floor = ? WHERE id = ?", (result["floor_area"], project_id))
            db.commit()
            flash(_("Mesures enregistrées."), "ok")
            return back
        if action == "plan":
            if g.project_role not in ("owner", "chef"):
                abort(403)
            last = db.execute("SELECT * FROM plan_readings WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
            if last is None:
                abort(400)
            q = plan_quantities(json.loads(last["result"]))
            n = 0
            for kind in request.form.getlist("kind"):
                if kind in q:
                    st = get_step(project_id, to_int(request.form.get(f"step_{kind}")))
                    add_to_plan(db, project_id, st, q[kind]["result"]["lines"])
                    n += 1
            if n:
                log(project_id, L("Prévu des matériaux complété à partir de la lecture du plan (%(n)s calcul(s))", n=n))
            db.commit()
            flash(_("Quantités ajoutées au prévu."), "ok")
            return redirect(url_for("project_stock", project_id=project_id) if g.project_role in ("owner", "chef") else url_for("plan_reading", project_id=project_id))
    last = db.execute("SELECT * FROM plan_readings WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    reading = json.loads(last["result"]) if last else None
    return render_template("plan_reading.html", p=p, role=g.project_role, plans=plans, reading=reading,
                           read_at=last["created_at"] if last else None, quantities=plan_quantities(reading) if reading else {},
                           steps=steps, ai=VISION.ai_enabled(), CALC_TYPES=CALC.TYPES)


# --------------------------------------------------------------------------
# Entrepreneurs verifies : profil, historique mesure, avis des proprietaires
# --------------------------------------------------------------------------
def is_contractor(u):
    return u is not None and (u["role"] == "chef" or (u["role"] == "pro" and u["profession"] == "entrepreneur"))


def contractor_projects(db, uid):
    return db.execute("SELECT * FROM projects WHERE chef_id = ? OR id IN (SELECT project_id FROM project_members WHERE "
                      "user_id = ? AND role = 'entrepreneur') ORDER BY id DESC", (uid, uid)).fetchall()


def contractor_record(db, uid):
    """Historique mesure par l'application sur tous les chantiers de l'entrepreneur. Rien n'est declaratif."""
    projects = contractor_projects(db, uid)
    rec = {"projects": len(projects), "finished": 0, "ongoing": 0, "amount": 0, "delays": [], "trusts": [],
           "nonconform": 0, "checks": 0, "proofs": 0, "refused": 0, "late_projects": 0}
    for p in projects:
        s = project_stats(p["id"], db)
        if not s["steps"]:
            continue
        rec["amount"] += s["total"]
        done = all(st["status"] in ("paye", "versement") for st in s["steps"])
        rec["finished" if done else "ongoing"] += 1
        pred = project_prediction(p, s, db)
        if pred is not None:
            delay = max(0, pred["delay"])
            rec["delays"].append(delay)
            rec["late_projects"] += delay > 15
        t = project_trust(p, s, pred, db)
        if t["score"] is not None:
            rec["trusts"].append(t["score"])
        rec["proofs"] += s["proofs_total"]
        rec["refused"] += s["refused"]
        row = db.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN status = 'non_conforme' THEN 1 ELSE 0 END) AS nc FROM step_checks "
                         "WHERE project_id = ? AND status != 'a_faire'", (p["id"],)).fetchone()
        rec["checks"] += row["n"] or 0
        rec["nonconform"] += row["nc"] or 0
        rec["nonconform"] += db.execute("SELECT COUNT(*) FROM inspections WHERE project_id = ? AND verdict = 'non_conforme'",
                                        (p["id"],)).fetchone()[0]
    rev = db.execute("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM contractor_reviews WHERE contractor_id = ?", (uid,)).fetchone()
    rec["reviews"] = rev["n"] or 0
    rec["rating"] = round(float(rev["avg"]), 1) if rev["avg"] is not None else None
    rec["avg_delay"] = round(sum(rec["delays"]) / len(rec["delays"])) if rec["delays"] else None
    rec["trust"] = round(sum(rec["trusts"]) / len(rec["trusts"])) if rec["trusts"] else None
    rec["refused_pct"] = round(rec["refused"] * 100 / rec["proofs"]) if rec["proofs"] else None
    return rec


def can_see_contractor(db, me, u):
    if u is None or not is_contractor(u) or u["deleted"]:
        return False
    if me["is_admin"] or me["id"] == u["id"] or (u["verified"] and u["verify_requested"]):
        return True
    return any(project_role(p) == "owner" for p in contractor_projects(db, u["id"]))


@app.route("/entrepreneurs")
@login_required
def contractors():
    db = get_db()
    q = request.args.get("zone", "").strip()[:60]
    rows = db.execute("SELECT * FROM users WHERE verified = 1 AND verify_requested = 1 AND blocked = 0 AND deleted = 0 AND "
                      "(role = 'chef' OR (role = 'pro' AND profession = 'entrepreneur')) ORDER BY name").fetchall()
    if q:
        rows = [u for u in rows if MAT.plain(q) in MAT.plain(u["zone"] or "")]
    items = [(u, contractor_record(db, u["id"])) for u in rows]
    items.sort(key=lambda x: (-(x[1]["trust"] or 0), -(x[1]["rating"] or 0)))
    return render_template("contractors.html", items=items, zone=q)


@app.route("/entrepreneurs/<int:uid>", methods=["GET", "POST"])
@login_required
def contractor(uid):
    db = get_db()
    me = current_user()
    u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not can_see_contractor(db, me, u):
        abort(404)
    mine = [p for p in user_projects(me) if me["role"] == "proprio" and project_role(p) == "owner" and not p["chef_id"]] \
        if me["role"] == "proprio" else []
    if request.method == "POST":
        pid = to_int(request.form.get("project_id"))
        p = next((x for x in mine if x["id"] == pid), None)
        if p is None or not (u["verified"] and u["verify_requested"]):
            abort(403)
        notify(p["id"], [uid], L("Invitation sur un chantier"),
               L("%(n)s vous invite sur le chantier « %(p)s » (%(a)s). Code pour le rejoindre : %(c)s", n=me["name"], p=p["name"],
                 a=p["address"] or "", c=p["invite_code"]), "/rejoindre", important=True, db=db)
        log(p["id"], L("%(n)s invité comme chef de chantier", n=u["name"]), db)
        db.commit()
        flash(_("Invitation envoyée avec le code du chantier."), "ok")
        return redirect(url_for("contractor", uid=uid))
    reviews = db.execute("SELECT r.*, a.name AS author, p.name AS project_name FROM contractor_reviews r JOIN users a ON "
                         "a.id = r.author_id JOIN projects p ON p.id = r.project_id WHERE r.contractor_id = ? ORDER BY r.id DESC",
                         (uid,)).fetchall()
    return render_template("contractor.html", u=u, rec=contractor_record(db, uid), reviews=reviews, mine=mine,
                           listed=bool(u["verified"] and u["verify_requested"]))


@app.route("/chantiers/<int:project_id>/avis", methods=["POST"])
@login_required
def contractor_review(project_id):
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    if not p["chef_id"]:
        abort(400)
    if not db.execute("SELECT 1 FROM steps WHERE project_id = ? AND status IN ('paye', 'versement')", (project_id,)).fetchone():
        flash(_("Vous pourrez noter le chef de chantier après le paiement d'une première étape."), "error")
        return redirect(url_for("project", project_id=project_id))
    rating = to_int(request.form.get("rating"))
    if not 1 <= rating <= 5:
        abort(400)
    me = current_user()
    comment = request.form.get("comment", "").strip()[:600] or None
    db.execute("DELETE FROM contractor_reviews WHERE project_id = ? AND author_id = ?", (project_id, me["id"]))
    db.execute("INSERT INTO contractor_reviews (project_id, author_id, contractor_id, rating, comment, created_at) "
               "VALUES (?,?,?,?,?,?)", (project_id, me["id"], p["chef_id"], rating, comment, now_iso()))
    notify(project_id, [p["chef_id"]], L("Nouvel avis sur votre travail"), L("%(n)s/5 sur le chantier « %(p)s »", n=rating, p=p["name"]),
           f"/entrepreneurs/{p['chef_id']}", db=db)
    db.commit()
    flash(_("Merci, votre avis est publié sur le profil du chef de chantier."), "ok")
    return redirect(url_for("project", project_id=project_id))


# --------------------------------------------------------------------------
# Controle visuel de la qualite des ouvrages
# --------------------------------------------------------------------------
QUALITY_ROLES = ("owner", "chef", "inspecteur", "intervenant", "admin")
QUALITY_EXPERTS = ("architecte", "conducteur", "ingenieur", "controleur")
Q_RANK = {"probleme": 0, "a_verifier": 1, "a_controler": 2, "non_visible": 3, "ok": 4}


def q_shooter(role):
    return role in ("chef", "inspecteur") or (role == "intervenant" and g.get("member_role") == "conducteur")


def q_expert(role):
    return role == "inspecteur" or (role == "intervenant" and g.get("member_role") in QUALITY_EXPERTS)


def q_starter(role):
    return role in ("owner", "chef", "inspecteur") or q_expert(role)


def q_review(rid):
    r = get_db().execute("SELECT * FROM quality_reviews WHERE id = ?", (rid,)).fetchone()
    if r is None:
        abort(404)
    p = load_project(r["project_id"], roles=QUALITY_ROLES)
    return r, p


def q_label(ouvrage, point, stored=None):
    o = QUAL.BY_SLUG.get(ouvrage)
    c = next((x for x in o["points"] if x["id"] == point), None) if o else None
    return QUAL._p(c["label"], g.get("lang", "fr")) if c else I18N.render(stored or point)


def q_effective(pt):
    """Statut retenu : avis du professionnel, sinon controle du proprietaire, sinon mesure ou IA."""
    if pt["expert_status"]:
        return pt["expert_status"]
    if pt["owner_status"] in ("ok", "probleme", "a_verifier"):
        return pt["owner_status"]
    return pt["status"]


def q_points(db, rid, lang=None):
    """Points d'un controle, numerotes dans l'ordre d'affichage : problemes d'abord, puis par gravite."""
    lang = lang or g.get("lang", "fr")
    r = db.execute("SELECT ouvrage FROM quality_reviews WHERE id = ?", (rid,)).fetchone()
    cat = {pt["id"]: pt for pt in QUAL.BY_SLUG[r["ouvrage"]]["points"]} if r else {}
    rows = []
    for x in db.execute("SELECT * FROM quality_points WHERE review_id = ? ORDER BY id", (rid,)):
        d = dict(x)
        d["effective"] = q_effective(x)
        d["accepted"] = x["owner_status"] == "accepte"
        c = cat.get(x["point"])
        if c:
            d["label"] = QUAL._p(c["label"], lang)
            d["look"] = QUAL._p(c["look"], lang)
        d["zone_box"] = json.loads(x["zone"]) if x["zone"] else None
        rows.append(d)
    rows.sort(key=lambda d: (d["accepted"], Q_RANK.get(d["effective"], 5), -QUAL.SEVERITY.get(d["severity"], 1), d["id"]))
    for i, d in enumerate(rows, 1):
        d["num"] = i
    return rows


def q_open_issues(db, step_id=None, project_id=None):
    """Problemes probables non resolus : dernier controle de chaque chaine, pas clos, pas accepte par le proprietaire."""
    where, args = ("r.step_id = ?", (step_id,)) if step_id else ("r.project_id = ?", (project_id,))
    rows = db.execute(
        "SELECT q.*, r.id AS rid, r.ouvrage FROM quality_points q JOIN quality_reviews r ON r.id = q.review_id "
        f"WHERE {where} AND r.status = 'pret' AND NOT EXISTS (SELECT 1 FROM quality_reviews n WHERE n.previous_id = r.id) "
        "AND (q.owner_status IS NULL OR q.owner_status != 'accepte')", args).fetchall()
    return [x for x in rows if q_effective(x) == "probleme"]


def q_quota(db, p):
    """(limite du mois ou None si illimite, analyses deja faites ce mois)."""
    used = db.execute("SELECT COUNT(*) FROM quality_reviews r JOIN projects pr ON pr.id = r.project_id "
                      "WHERE pr.owner_id = ? AND r.mode = 'ia' AND r.analysed_at LIKE ?",
                      (p["owner_id"], QUAL.now_month() + "%")).fetchone()[0]
    if not billing_enforced():
        return None, used
    owner = db.execute("SELECT * FROM users WHERE id = ?", (p["owner_id"],)).fetchone()
    v = sub_view(db, owner)
    if v is None or v["blocked"]:
        return 0, used
    return BILL.QUALITY_AI_MONTH.get(v["plan"], 0), used


def q_ai_allowed(db, p):
    if not QUAL.ai_enabled() or get_setting("quality_ai", "1") != "1":
        return False
    limit, used = q_quota(db, p)
    return limit is None or used < limit


def q_photo_rows(db, rid):
    return db.execute("SELECT qp.*, pr.ok, pr.reasons, pr.created_at AS taken, pr.note, pr.kind, pr.filename, pr.thumb, pr.zone_id "
                      "FROM quality_photos qp JOIN proofs pr ON pr.id = qp.proof_id WHERE qp.review_id = ? ORDER BY qp.id",
                      (rid,)).fetchall()


def q_pick_photos(o, rows):
    """Photos envoyees a l'analyse : les obligatoires d'abord, au plus 2 par prise de vue, MAX_PHOTOS en tout."""
    order = {s["id"]: i for i, s in enumerate(o["shots"])}
    good = [r for r in rows if r["ok"]]
    by_shot = {}
    for r in reversed(good):
        by_shot.setdefault(r["shot"], [])
        if len(by_shot[r["shot"]]) < 2:
            by_shot[r["shot"]].append(r)
    req = {s["id"] for s in o["shots"] if s["required"]}
    keys = sorted(by_shot, key=lambda k: (k not in req, order.get(k, 99)))
    out = [rs[0] for k in keys for rs in [by_shot[k]]] + [rs[1] for k in keys for rs in [by_shot[k]] if len(rs) > 1]
    return out[:QUAL.MAX_PHOTOS]


def run_quality_analysis(rid, use_ai):
    db = connect()
    try:
        r = db.execute("SELECT * FROM quality_reviews WHERE id = ?", (rid,)).fetchone()
        o = QUAL.BY_SLUG[r["ouvrage"]]
        lang = r["lang"] or "fr"
        p = db.execute("SELECT * FROM projects WHERE id = ?", (r["project_id"],)).fetchone()
        st = db.execute("SELECT name FROM steps WHERE id = ?", (r["step_id"],)).fetchone() if r["step_id"] else None
        shots = {s["id"]: QUAL._p(s["label"], "fr") for s in o["shots"]}
        zones = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM zones WHERE project_id = ?", (p["id"],))}
        picked = q_pick_photos(o, q_photo_rows(db, rid))
        images, photos = [], []
        for row in picked:
            path = os.path.join(UPLOAD_DIR, row["filename"] if row["kind"] != "video" else (row["thumb"] or row["filename"]))
            try:
                images.append(Image.open(path))
            except Exception:
                continue
            photos.append({"proof_id": row["proof_id"], "shot_label": shots.get(row["shot"], row["shot"]),
                           "note": I18N.render(row["note"] or "")[:200], "taken": (row["taken"] or "")[:16].replace("T", " "),
                           "zone": zones.get(row["zone_id"])})
        values = json.loads(r["measures"] or "{}")
        rules = QUAL.rule_results(r["ouvrage"], values, lang)
        previous = []
        if r["previous_id"]:
            previous = [dict(x) for x in db.execute("SELECT * FROM quality_points WHERE review_id = ?", (r["previous_id"],))
                        if q_effective(x) in ("probleme", "a_verifier") and x["owner_status"] != "accepte"]
        ai, mode, err = None, "regles", None
        if use_ai and images:
            try:
                ai = QUAL.call_ai(o, images, photos, values, rules, previous,
                                  I18N.render(st["name"], "fr") if st else "", lang)
                mode = "ia"
            except Exception as e:  # l'IA ne doit jamais bloquer : on garde les mesures
                err = str(e)[:300]
        points = QUAL.merge(o, ai, rules, len(images), lang)
        fixed = {}
        for pv in previous:
            new = next((x for x in points if x["point"] == pv["point"]), None)
            if new and new["status"] == "ok":
                fixed[pv["point"]] = "corrige"
            elif new and new["status"] == "probleme":
                fixed[pv["point"]] = "pas_corrige"
        for c in (ai or {}).get("corrige") or []:
            if isinstance(c, dict) and c.get("statut") in ("corrige", "pas_corrige") and c.get("point") in {pv["point"] for pv in previous}:
                if not (c["statut"] == "corrige" and fixed.get(c["point"]) == "pas_corrige"):   # une mesure mauvaise l'emporte
                    fixed[c["point"]] = c["statut"]
        db.execute("DELETE FROM quality_points WHERE review_id = ?", (rid,))
        for x in points:
            proof_id = photos[x["photo"]]["proof_id"] if x["photo"] is not None else None
            db.execute("INSERT INTO quality_points (review_id, point, label, severity, status, source, confidence, proof_id, zone, "
                       "explanation, advice, question, measure_note, extra, fixed, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rid, x["point"], x["label"], x["severity"], x["status"], x["source"], x["confidence"], proof_id,
                        json.dumps(x["zone"]) if x["zone"] else None, x["explanation"], x["advice"], x["question"],
                        x["measure_note"], x["extra"], fixed.get(x["point"]), now_iso()))
        sc, judged = QUAL.score(points)
        counts = {k: sum(1 for x in points if x["status"] == k) for k in ("ok", "a_verifier", "probleme", "non_visible", "a_controler")}
        fr = lang != "en"
        summary = str((ai or {}).get("resume") or "")[:800] or (
            (f"{counts['ok']} point(s) semblent corrects, {counts['a_verifier']} à vérifier, {counts['probleme']} problème(s) probable(s). "
             f"{counts['a_controler']} point(s) restent à contrôler vous-même sur les photos." if fr else
             f"{counts['ok']} point(s) look right, {counts['a_verifier']} to check, {counts['probleme']} likely problem(s). "
             f"{counts['a_controler']} point(s) are left for you to check on the photos."))
        unusable = []
        for u in (ai or {}).get("photos_inutilisables") or []:
            i = QUAL._photo_idx((u or {}).get("photo"), len(photos)) if isinstance(u, dict) else None
            if i is not None:
                unusable.append({"proof_id": photos[i]["proof_id"], "reason": str(u.get("raison") or "")[:200]})
        readings = []
        for m in (ai or {}).get("mesures_lues") or []:
            if isinstance(m, dict) and m.get("mesure"):
                readings.append({"measure": str(m["mesure"])[:40], "value": str(m.get("valeur_lue") or "")[:60],
                                 "coherent": m.get("coherent"), "comment": str(m.get("commentaire") or "")[:300]})
        extras = {"unusable": unusable, "readings": readings, "counts": counts,
                  "more": [str(x)[:200] for x in ((ai or {}).get("photos_a_ajouter") or [])][:6]}
        inspect = QUAL.needs_inspection(points, ai) or any(rd["coherent"] is False for rd in readings)
        same = (ai or {}).get("meme_lieu")
        db.execute("UPDATE quality_reviews SET status = 'pret', mode = ?, analysed_at = ?, score = ?, judged = ?, summary = ?, "
                   "inspect = ?, same_place = ?, extras = ?, ai_raw = ?, error = ?, analysed_photos = ? WHERE id = ?",
                   (mode, now_iso(), sc, judged, summary, int(inspect), None if same is None else int(bool(same)),
                    json.dumps(extras, ensure_ascii=False), json.dumps(ai, ensure_ascii=False)[:60000] if ai else None,
                    err, len(images), rid))
        db.commit()
        o_name = QUAL._p(o["name"], lang)
        with app.test_request_context():
            g.lang = lang
            body = L("%(o)s : %(p)s problème(s) probable(s), %(v)s point(s) à vérifier.", o=o_name, p=counts["probleme"],
                     v=counts["a_verifier"] + counts["a_controler"])
            path = f"/qualite/{rid}"
            notify(p["id"], owners_of(p, db), L("Contrôle qualité prêt"), body, path, important=counts["probleme"] > 0, db=db)
            if counts["probleme"] and p["chef_id"]:
                notify(p["id"], [p["chef_id"]], L("Contrôle qualité : points à reprendre"), body, path, db=db)
            if same is False:
                notify(p["id"], owners_of(p, db), L("Photos douteuses selon l'IA"),
                       L("Les photos du contrôle « %(o)s » ne semblent pas montrer le même ouvrage.", o=o_name), path,
                       important=True, db=db)
            log(p["id"], L("Contrôle qualité « %(o)s » analysé", o=o_name), db=db)
        db.commit()
    except Exception as e:
        db.execute("UPDATE quality_reviews SET status = 'erreur', error = ? WHERE id = ?", (str(e)[:300], rid))
        db.commit()
    finally:
        db.close()


@app.route("/chantiers/<int:project_id>/qualite", methods=["GET", "POST"])
@login_required
def quality_list(project_id):
    p = load_project(project_id, roles=QUALITY_ROLES)
    role = g.project_role
    db = get_db()
    stats = project_stats(project_id)
    if request.method == "POST":
        if not q_starter(role):
            abort(403)
        slug = request.form.get("ouvrage")
        if slug not in QUAL.BY_SLUG:
            flash(_("Choisissez l'ouvrage à contrôler."), "error")
            return redirect(url_for("quality_list", project_id=project_id))
        step_id = to_int(request.form.get("step_id"), None)
        if not step_id or not db.execute("SELECT 1 FROM steps WHERE id = ? AND project_id = ?", (step_id, project_id)).fetchone():
            step_id = stats["current"]["id"] if stats["current"] else None
        zone_id = to_int(request.form.get("zone_id"), None)
        if zone_id and not db.execute("SELECT 1 FROM zones WHERE id = ? AND project_id = ?", (zone_id, project_id)).fetchone():
            zone_id = None
        owner = db.execute("SELECT lang FROM users WHERE id = ?", (p["owner_id"],)).fetchone()
        cur = db.execute("INSERT INTO quality_reviews (project_id, step_id, zone_id, ouvrage, label, lang, created_by, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?)", (project_id, step_id, zone_id, slug, request.form.get("label", "").strip()[:80] or None,
                                                      (owner["lang"] if owner and owner["lang"] else g.lang), current_user()["id"], now_iso()))
        rid = cur.lastrowid
        name = QUAL._p(QUAL.BY_SLUG[slug]["name"], "fr")
        log(project_id, L("Contrôle qualité ouvert : %(o)s", o=name))
        if role != "chef" and p["chef_id"]:
            notify(project_id, [p["chef_id"]], L("Photos de contrôle demandées"),
                   L("Prenez les photos guidées pour le contrôle « %(o)s ».", o=name), f"/qualite/{rid}", important=True)
        db.commit()
        return redirect(url_for("quality_page", rid=rid))
    reviews = db.execute("SELECT r.*, st.name AS step_name, (SELECT COUNT(*) FROM quality_photos qp WHERE qp.review_id = r.id) AS n_photos "
                         "FROM quality_reviews r LEFT JOIN steps st ON st.id = r.step_id WHERE r.project_id = ? ORDER BY r.id DESC",
                         (project_id,)).fetchall()
    issues = {}
    for x in q_open_issues(db, project_id=project_id):
        issues[x["rid"]] = issues.get(x["rid"], 0) + 1
    current = stats["current"]
    suggested = QUAL.suggest(I18N.render(current["name"], "fr")) if current else []
    names = {o["slug"]: o["name"] for o in QUAL.catalog(g.lang)}
    limit, used = q_quota(db, p)
    return render_template("quality_list.html", p=p, role=role, reviews=reviews, issues=issues, catalog=QUAL.catalog(g.lang),
                           names=names, suggested=suggested, steps=stats["steps"], current=current,
                           zones=project_zones(db, project_id), can_start=q_starter(role), ai_on=QUAL.ai_enabled(),
                           quota_limit=limit, quota_used=used)


@app.route("/qualite/<int:rid>")
@login_required
def quality_page(rid):
    r, p = q_review(rid)
    role = g.project_role
    db = get_db()
    o = QUAL.localize(QUAL.BY_SLUG[r["ouvrage"]], g.lang)
    rows = q_photo_rows(db, rid)
    shot_names = {s["id"]: s["label"] for s in o["shots"]}
    photos = []
    for x in rows:
        q = json.loads(x["quality"] or "{}")
        photos.append(dict(x, shot_label=shot_names.get(x["shot"], _("Autre photo")),
                           issues=[QUAL._p(QUAL.ISSUE_LABEL[i], g.lang) for i in q.get("issues", []) if i in QUAL.ISSUE_LABEL],
                           reasons_txt="; ".join(I18N.render_list(x["reasons"])) if not x["ok"] else ""))
    done = {}
    for x in photos:
        if x["ok"]:
            done[x["shot"]] = done.get(x["shot"], 0) + 1
    missing = [s for s in o["shots"] if s["required"] and not done.get(s["id"])]
    values = json.loads(r["measures"] or "{}")
    live_rules = QUAL.rule_results(r["ouvrage"], values, g.lang)
    points = q_points(db, rid)
    eff = [{"status": d["effective"] if not d["accepted"] else "ok", "severity": d["severity"]} for d in points]
    score, judged = QUAL.score(eff) if points else (None, 0)
    extras = json.loads(r["extras"] or "{}")
    messages = db.execute("SELECT m.*, u.name AS author FROM quality_messages m JOIN users u ON u.id = m.user_id "
                          "WHERE m.review_id = ? ORDER BY m.id", (rid,)).fetchall()
    prev = db.execute("SELECT id, analysed_at FROM quality_reviews WHERE id = ?", (r["previous_id"],)).fetchone() if r["previous_id"] else None
    nxt = db.execute("SELECT id FROM quality_reviews WHERE previous_id = ? ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
    step = db.execute("SELECT * FROM steps WHERE id = ?", (r["step_id"],)).fetchone() if r["step_id"] else None
    zone = db.execute("SELECT name FROM zones WHERE id = ?", (r["zone_id"],)).fetchone() if r["zone_id"] else None
    new_photos = r["analysed_at"] and any(x["ok"] and x["created_at"] > r["analysed_at"] for x in photos)
    limit, used = q_quota(db, p)
    ctx = dict(r=r, p=p, o=o, role=role, photos=photos, done=done, missing=missing, values=values, live_rules=live_rules,
               points=points, score=score, judged=judged, extras=extras, messages=messages, prev=prev, nxt=nxt, step=step,
               zone=zone, new_photos=new_photos, shooter=q_shooter(role), expert=q_expert(role), is_owner=role == "owner",
               ai_on=QUAL.ai_enabled() and get_setting("quality_ai", "1") == "1", ai_allowed=q_ai_allowed(db, p),
               quota_limit=limit, quota_used=used, QSTATUS={k: QUAL._p(v, g.lang) for k, v in QUAL.STATUS_LABEL.items()},
               QSOURCE={k: QUAL._p(v, g.lang) for k, v in QUAL.SOURCE_LABEL.items()},
               QSEV={k: QUAL._p(v, g.lang) for k, v in QUAL.SEVERITY_LABEL.items()},
               preselect=request.args.get("prise"), zones=project_zones(db, p["id"]))
    if ctx["shooter"] and r["status"] != "clos":
        ctx["capture_token"] = new_capture_token(db, p["id"])
    return render_template("quality_review.html", **ctx)


@app.route("/qualite/<int:rid>/photo", methods=["POST"])
@login_required
def quality_photo(rid):
    r, p = q_review(rid)
    if not q_shooter(g.project_role) or r["status"] == "clos":
        abort(403)
    db = get_db()
    o = QUAL.BY_SLUG[r["ouvrage"]]
    shot_id = request.form.get("shot")
    if shot_id not in {s["id"] for s in o["shots"]}:
        shot_id = "autre"
    st = (db.execute("SELECT * FROM steps WHERE id = ?", (r["step_id"],)).fetchone() if r["step_id"] else None) \
        or project_stats(p["id"])["current"] \
        or db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position DESC LIMIT 1", (p["id"],)).fetchone()
    if st is None:
        flash(_("Ce chantier n'a pas encore d'étape."), "error")
        return redirect(url_for("quality_page", rid=rid))
    ok, reasons = process_proof(p, st, current_user(), source="chef" if g.project_role == "chef" else "inspecteur")
    if ok is None:
        flash(reasons, "error")
        return redirect(url_for("quality_page", rid=rid, prise=shot_id))
    proof_id = g.last_proof_id
    pr = db.execute("SELECT * FROM proofs WHERE id = ?", (proof_id,)).fetchone()
    label = next((QUAL._p(s["label"], "fr") for s in o["shots"] if s["id"] == shot_id), "Autre photo")
    if not (pr["note"] or "").strip():
        db.execute("UPDATE proofs SET note = ? WHERE id = ?", (f"Contrôle qualité : {label}", proof_id))
    quality = None
    try:
        quality = QUAL.photo_quality(Image.open(os.path.join(UPLOAD_DIR, pr["filename"] if pr["kind"] != "video" else pr["thumb"])))
    except Exception:
        pass
    db.execute("INSERT INTO quality_photos (review_id, proof_id, shot, quality, created_at) VALUES (?,?,?,?,?)",
               (rid, proof_id, shot_id, json.dumps(quality) if quality else None, now_iso()))
    db.commit()
    if not ok:
        flash(_('Photo refusée : ') + "; ".join(map(I18N.render, reasons)), "error")
    elif quality and quality["issues"]:
        flash(_("Photo enregistrée, mais elle risque d'être inutilisable (%(i)s) : reprenez-la si possible.",
                i=", ".join(QUAL._p(QUAL.ISSUE_LABEL[i], g.lang) for i in quality["issues"])), "error")
    else:
        flash(_("Photo vérifiée et ajoutée au contrôle."), "ok")
    return redirect(url_for("quality_page", rid=rid, _anchor="prises"))


@app.route("/qualite/<int:rid>/mesures", methods=["POST"])
@login_required
def quality_measures(rid):
    r, p = q_review(rid)
    if not (q_shooter(g.project_role) or q_expert(g.project_role)) or r["status"] == "clos":
        abort(403)
    o = QUAL.BY_SLUG[r["ouvrage"]]
    values = {}
    for m in o["measures"]:
        v = request.form.get(m["id"], "").strip()[:200]
        if m["rule"] == "choice" and v not in {k for k, _l, _s in m["choices"]}:
            v = ""
        if v:
            values[m["id"]] = v
        if m["rule"] == "min_ref":
            ref = request.form.get(m["id"] + "_ref", "").strip()[:20]
            if ref:
                values[m["id"] + "_ref"] = ref
    db = get_db()
    db.execute("UPDATE quality_reviews SET measures = ?, measures_by = ?, measures_at = ? WHERE id = ?",
               (json.dumps(values, ensure_ascii=False), current_user()["id"], now_iso(), rid))
    db.commit()
    flash(_("Mesures enregistrées."), "ok")
    return redirect(url_for("quality_page", rid=rid, _anchor="mesures"))


@app.route("/qualite/<int:rid>/analyser", methods=["POST"])
@login_required
def quality_analyse(rid):
    r, p = q_review(rid)
    role = g.project_role
    if not (role == "owner" or q_shooter(role) or q_expert(role)) or r["status"] in ("clos", "analyse"):
        abort(403)
    db = get_db()
    o = QUAL.BY_SLUG[r["ouvrage"]]
    ok_rows = [x for x in q_photo_rows(db, rid) if x["ok"]]
    if not ok_rows and not r["measures"]:
        flash(_("Ajoutez d'abord des photos vérifiées ou des mesures."), "error")
        return redirect(url_for("quality_page", rid=rid))
    use_ai = q_ai_allowed(db, p) and bool(ok_rows)
    if QUAL.ai_enabled() and ok_rows and not use_ai and get_setting("quality_ai", "1") == "1":
        flash(_("Analyses par l'IA de ce mois épuisées pour cette offre : le contrôle se fait sur les mesures et par vous-même. "
                "Passez à l'offre Pro pour en avoir davantage."), "error")
    db.execute("UPDATE quality_reviews SET status = 'analyse', error = NULL WHERE id = ?", (rid,))
    db.commit()
    run_async(run_quality_analysis, rid, use_ai)
    flash(_("Analyse lancée : le résultat apparaît ici dans une à deux minutes.") if use_ai else _("Contrôle calculé."), "ok")
    return redirect(url_for("quality_page", rid=rid))


@app.route("/qualite/<int:rid>/points/<int:qid>", methods=["POST"])
@login_required
def quality_point(rid, qid):
    r, p = q_review(rid)
    role = g.project_role
    db = get_db()
    pt = db.execute("SELECT * FROM quality_points WHERE id = ? AND review_id = ?", (qid, rid)).fetchone()
    if pt is None:
        abort(404)
    action = request.form.get("action")
    note = request.form.get("note", "").strip()[:800] or None
    back = redirect(url_for("quality_page", rid=rid, _anchor=f"q{qid}"))
    me = current_user()
    label = q_label(r["ouvrage"], pt["point"], pt["label"])
    if action in ("owner_check", "accept", "reset", "ask") and role != "owner":
        abort(403)
    if action == "owner_check":
        st = request.form.get("status")
        if st not in ("ok", "a_verifier", "probleme"):
            abort(400)
        db.execute("UPDATE quality_points SET owner_status = ?, owner_note = ?, updated_at = ? WHERE id = ?", (st, note, now_iso(), qid))
    elif action == "accept":
        db.execute("UPDATE quality_points SET owner_status = 'accepte', owner_note = ?, updated_at = ? WHERE id = ?", (note, now_iso(), qid))
        log(p["id"], L("Contrôle qualité : « %(l)s » accepté par le propriétaire", l=label))
    elif action == "reset":
        db.execute("UPDATE quality_points SET owner_status = NULL, owner_note = NULL, updated_at = ? WHERE id = ?", (now_iso(), qid))
    elif action == "ask":
        body = note or I18N.render(pt["question"] or "") or _("Envoyez une photo de plus pour ce point.")
        db.execute("INSERT INTO quality_messages (review_id, point_id, user_id, kind, body, created_at) VALUES (?,?,?,?,?,?)",
                   (rid, qid, me["id"], "demande", body, now_iso()))
        who = [p["chef_id"]] + [m[0] for m in db.execute("SELECT user_id FROM project_members WHERE project_id = ? AND role = 'conducteur'",
                                                          (p["id"],))]
        notify(p["id"], who, L("Question sur le contrôle qualité"), L("%(l)s : %(b)s", l=label, b=body[:300]),
               f"/qualite/{rid}#q{qid}", important=True)
    elif action == "expert":
        if not q_expert(role):
            abort(403)
        st = request.form.get("status")
        if st not in ("ok", "a_verifier", "probleme"):
            abort(400)
        db.execute("UPDATE quality_points SET expert_status = ?, expert_note = ?, expert_by = ?, expert_at = ?, updated_at = ? "
                   "WHERE id = ?", (st, note, me["id"], now_iso(), now_iso(), qid))
        notify(p["id"], owners_of(p), L("Avis d'un professionnel"),
               L("%(n)s donne son avis sur « %(l)s ».", n=me["name"], l=label), f"/qualite/{rid}#q{qid}")
        log(p["id"], L("Contrôle qualité : avis de %(n)s sur « %(l)s »", n=me["name"], l=label))
    else:
        abort(400)
    db.commit()
    return back


@app.route("/qualite/<int:rid>/messages", methods=["POST"])
@login_required
def quality_message(rid):
    r, p = q_review(rid)
    role = g.project_role
    if not (role == "owner" or q_shooter(role) or q_expert(role)):
        abort(403)
    body = request.form.get("body", "").strip()[:1500]
    if len(body) < 2:
        flash(_("Écrivez votre message."), "error")
        return redirect(url_for("quality_page", rid=rid, _anchor="echanges"))
    db = get_db()
    qid = to_int(request.form.get("point_id"), None)
    if qid and not db.execute("SELECT 1 FROM quality_points WHERE id = ? AND review_id = ?", (qid, rid)).fetchone():
        qid = None
    db.execute("INSERT INTO quality_messages (review_id, point_id, user_id, kind, body, created_at) VALUES (?,?,?,?,?,?)",
               (rid, qid, current_user()["id"], "reponse" if role != "owner" else "demande", body, now_iso()))
    to = owners_of(p) if role != "owner" else [p["chef_id"]]
    notify(p["id"], to, L("Contrôle qualité : nouveau message"), body[:300], f"/qualite/{rid}#echanges")
    db.commit()
    return redirect(url_for("quality_page", rid=rid, _anchor="echanges"))


@app.route("/qualite/<int:rid>/contre-visite", methods=["POST"])
@login_required
def quality_followup(rid):
    r, p = q_review(rid)
    if g.project_role not in ("owner", "chef") or r["status"] != "pret":
        abort(403)
    db = get_db()
    nxt = db.execute("SELECT id FROM quality_reviews WHERE previous_id = ?", (rid,)).fetchone()
    if nxt:
        return redirect(url_for("quality_page", rid=nxt["id"]))
    cur = db.execute("INSERT INTO quality_reviews (project_id, step_id, zone_id, ouvrage, label, lang, measures, previous_id, created_by, "
                     "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (r["project_id"], r["step_id"], r["zone_id"], r["ouvrage"], r["label"], r["lang"], r["measures"], rid,
                      current_user()["id"], now_iso()))
    new = cur.lastrowid
    todo = [x["label"] for x in q_points(db, rid) if x["effective"] in ("probleme", "a_verifier") and not x["accepted"]]
    name = QUAL._p(QUAL.BY_SLUG[r["ouvrage"]]["name"], "fr")
    if p["chef_id"] and current_user()["id"] != p["chef_id"]:
        notify(p["id"], [p["chef_id"]], L("Contre-visite demandée"),
               L("« %(o)s » : reprenez les points signalés puis refaites les photos (%(l)s).", o=name, l=", ".join(todo[:5])),
               f"/qualite/{new}", important=True)
    log(p["id"], L("Contre-visite qualité ouverte : %(o)s", o=name))
    db.commit()
    return redirect(url_for("quality_page", rid=new))


@app.route("/qualite/<int:rid>/clore", methods=["POST"])
@login_required
def quality_close(rid):
    r, p = q_review(rid)
    if g.project_role != "owner":
        abort(403)
    db = get_db()
    db.execute("UPDATE quality_reviews SET status = 'clos', closed_at = ?, closed_by = ? WHERE id = ?", (now_iso(), current_user()["id"], rid))
    db.commit()
    flash(_("Contrôle clos."), "ok")
    return redirect(url_for("quality_list", project_id=p["id"]))


@app.route("/qualite/<int:rid>/photos/<int:proof_id>/annotee")
@login_required
def quality_annotated(rid, proof_id):
    r, p = q_review(rid)
    db = get_db()
    pr = db.execute("SELECT * FROM proofs WHERE id = ? AND project_id = ?", (proof_id, p["id"])).fetchone()
    if pr is None:
        abort(404)
    marks = [(d["num"], d["effective"], d["zone_box"]) for d in q_points(db, rid) if d["proof_id"] == proof_id and d["zone_box"]]
    path = os.path.join(UPLOAD_DIR, pr["filename"] if pr["kind"] != "video" else (pr["thumb"] or pr["filename"]))
    data = QUAL.annotate(Image.open(path), marks)
    resp = app.response_class(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=60"
    return resp


def quality_by_step(db, project_id):
    """Pour la carte de chaque etape : dernier controle (note) et problemes ouverts."""
    out = {}
    for r in db.execute("SELECT id, step_id, score, status FROM quality_reviews WHERE project_id = ? AND step_id IS NOT NULL "
                        "ORDER BY id", (project_id,)):
        out.setdefault(r["step_id"], {"n": 0, "issues": 0, "score": None})
        out[r["step_id"]]["n"] += 1
        if r["status"] == "pret" and r["score"] is not None:
            out[r["step_id"]]["score"] = r["score"]
    for x in q_open_issues(db, project_id=project_id):
        sid = db.execute("SELECT step_id FROM quality_reviews WHERE id = ?", (x["rid"],)).fetchone()[0]
        if sid in out:
            out[sid]["issues"] += 1
    return out


# --------------------------------------------------------------------------
# WhatsApp pour le chef de chantier
# --------------------------------------------------------------------------
WA_PENDING_DIR = os.path.join(UPLOAD_DIR, "wa_attente")
FIN_DIR = os.path.join(UPLOAD_DIR, "financement")
VOICE_DIR = os.path.join(UPLOAD_DIR, "voix")


def as_user(user, fn, form=None, files=None, **kw):
    """Appelle une vue comme si l'utilisateur l'avait envoyee depuis l'application. Retourne les messages affiches."""
    data = dict(form or {})
    data.update(files or {})
    with app.test_request_context(method="POST", data=data, content_type="multipart/form-data"):
        saved_user, saved_lang = g.get("user"), g.get("lang")
        g.user, g.lang = user, user["lang"] or saved_lang or I18N.DEFAULT
        try:
            try:
                fn(**kw)
            except HTTPException as e:
                flash(str(e.description or e), "error")
            return get_flashed_messages(with_categories=True)
        finally:
            g.user, g.lang = saved_user, saved_lang


def wa_user(db, phone):
    for u in db.execute("SELECT * FROM users WHERE phone IS NOT NULL AND phone != '' AND deleted = 0 AND blocked = 0"):
        if NOTIFY.e164(u["phone"]) == phone:
            return u
    return None


def wa_projects(db, user):
    return db.execute("SELECT * FROM projects p WHERE chef_id = ? AND EXISTS (SELECT 1 FROM steps s WHERE s.project_id = p.id "
                      "AND s.status != 'paye') ORDER BY id DESC", (user["id"],)).fetchall()


def wa_session(db, phone):
    row = db.execute("SELECT * FROM wa_sessions WHERE phone = ?", (phone,)).fetchone()
    if row is None:
        db.execute("INSERT INTO wa_sessions (phone, updated_at) VALUES (?,?)", (phone, now_iso()))
        row = db.execute("SELECT * FROM wa_sessions WHERE phone = ?", (phone,)).fetchone()
    return dict(row)


def wa_save_session(db, sess):
    db.execute("UPDATE wa_sessions SET user_id = ?, project_id = ?, awaiting = ?, pending = ?, loc_lat = ?, loc_lng = ?, loc_at = ?, "
               "updated_at = ? WHERE phone = ?", (sess["user_id"], sess["project_id"], sess["awaiting"], sess["pending"],
                                                  sess["loc_lat"], sess["loc_lng"], sess["loc_at"], now_iso(), sess["phone"]))


def wa_log(db, direction, phone, kind, body, user=None, project_id=None):
    db.execute("INSERT INTO wa_messages (direction, phone, user_id, project_id, kind, body, created_at) VALUES (?,?,?,?,?,?,?)",
               (direction, phone, user["id"] if user else None, project_id, kind, (body or "")[:2000], now_iso()))


def wa_location_fresh(sess):
    if sess["loc_lat"] is None or not sess["loc_at"]:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(sess["loc_at"])).total_seconds() <= WA.LOCATION_MINUTES * 60


def wa_send_photo(db, user, p, raw, sess):
    """Photo recue par WhatsApp -> preuve, avec la position partagee. Retourne le message de reponse."""
    lang = user["lang"] or "fr"
    g.last_proof_id = None
    msgs = as_user(user, upload_proof, form={"lat": str(sess["loc_lat"]), "lng": str(sess["loc_lng"]), "acc": "30",
                                             "capture": "whatsapp", "tz_offset": "0", "note": "Reçue par WhatsApp"},
                   files={"photo": (io.BytesIO(raw), "whatsapp.jpg")}, project_id=p["id"])
    pid_ = g.get("last_proof_id")
    if not pid_:
        return WA.say(lang, "pas_etape") if any("Aucune étape" in m or "No ongoing" in m for _c, m in msgs) else \
            (msgs[0][1] if msgs else WA.say(lang, "media_erreur"))
    pr = db.execute("SELECT * FROM proofs WHERE id = ?", (pid_,)).fetchone()
    st = db.execute("SELECT name FROM steps WHERE id = ?", (pr["step_id"],)).fetchone()
    if not pr["ok"]:
        return WA.say(lang, "photo_refusee", raisons="; ".join(I18N.render_list(pr["reasons"], lang)))
    if pr["suspect"]:
        return WA.say(lang, "photo_suspect")
    return WA.say(lang, "photo_ok", etape=I18N.render(st["name"], lang) if st else "")


def wa_flush_pending(db, user, p, sess):
    """Photos en attente de position : envoyees si la position est arrivee a temps, sinon perimees."""
    pending = json.loads(sess["pending"] or "[]")
    if not pending:
        return []
    replies, expired = [], 0
    for item in pending:
        path = os.path.join(WA_PENDING_DIR, item["file"])
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["at"])).total_seconds()
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if age <= WA.LOCATION_MINUTES * 60 and item.get("project_id") == p["id"]:
            replies.append(wa_send_photo(db, user, p, raw, sess))
        else:
            expired += 1
        try:
            os.remove(path)
        except OSError:
            pass
    sess["pending"] = None
    if expired:
        replies.append(WA.say(user["lang"] or "fr", "photo_expiree", n=expired))
    return replies


def wa_add_note(db, user, p, kind, text=None, raw=None, ctype="audio/ogg"):
    st = project_stats(p["id"])["current"]
    filename = None
    if raw is not None:
        os.makedirs(VOICE_DIR, exist_ok=True)
        ext = "ogg" if "ogg" in ctype else "mp3" if "mpeg" in ctype else "m4a" if "mp4" in ctype or "aac" in ctype else "amr" if "amr" in ctype else "ogg"
        filename = f"{secrets.token_hex(12)}.{ext}"
        with open(os.path.join(VOICE_DIR, filename), "wb") as fh:
            fh.write(raw)
    cur = db.execute("INSERT INTO site_notes (project_id, user_id, step_id, channel, kind, filename, transcript, status, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (p["id"], user["id"], st["id"] if st else None, "whatsapp", kind, filename,
                                                    text, "en_cours" if kind == "vocal" else "pret", now_iso()))
    nid = cur.lastrowid
    db.commit()
    if kind == "vocal":
        run_async(process_voice_note, nid)
    else:
        finish_note(db, nid, text)
    return nid


def finish_note(db, nid, transcript, err=None):
    n = db.execute("SELECT * FROM site_notes WHERE id = ?", (nid,)).fetchone()
    p = db.execute("SELECT * FROM projects WHERE id = ?", (n["project_id"],)).fetchone()
    st = db.execute("SELECT name FROM steps WHERE id = ?", (n["step_id"],)).fetchone() if n["step_id"] else None
    owner_lang = (db.execute("SELECT lang FROM users WHERE id = ?", (p["owner_id"],)).fetchone()["lang"]) or "fr"
    summ = None
    if transcript:
        try:
            summ = VOICE.summarise(transcript, p["name"], I18N.render(st["name"], "fr") if st else "", owner_lang)
        except Exception as e:
            err = str(e)[:300]
            summ = VOICE.simple(transcript)
    db.execute("UPDATE site_notes SET transcript = ?, summary = ?, category = ?, urgent = ?, materials = ?, status = 'pret', "
               "error = ? WHERE id = ?", (transcript, summ["resume"] if summ else None, summ["categorie"] if summ else None,
                                          int(bool(summ and summ["urgent"])), json.dumps(summ["materiaux"], ensure_ascii=False) if summ else None,
                                          err, nid))
    chef = db.execute("SELECT name FROM users WHERE id = ?", (n["user_id"],)).fetchone()
    title = L("Note vocale du chef") if n["kind"] == "vocal" else L("Message du chef")
    text = (summ["resume"] if summ else None) or transcript
    body = L("%(n)s : %(b)s", n=chef["name"], b=text) if text else L("%(n)s a envoyé une note vocale à écouter.", n=chef["name"])
    with app.test_request_context():
        notify(p["id"], owners_of(p, db), title, body,
               f"/chantiers/{p['id']}/notes", important=bool(summ and summ["urgent"]), db=db)
        log(p["id"], L("Note vocale du chef") if n["kind"] == "vocal" else L("Message du chef"), db=db, user_id=n["user_id"])
    db.commit()


def process_voice_note(nid):
    db = connect()
    try:
        n = db.execute("SELECT * FROM site_notes WHERE id = ?", (nid,)).fetchone()
        text, err = None, None
        try:
            with open(os.path.join(VOICE_DIR, n["filename"]), "rb") as fh:
                text = VOICE.transcribe(fh.read(), n["filename"])
        except Exception as e:
            err = str(e)[:300]
        finish_note(db, nid, text, err)
    except Exception as e:
        db.execute("UPDATE site_notes SET status = 'erreur', error = ? WHERE id = ?", (str(e)[:300], nid))
        db.commit()
    finally:
        db.close()


def wa_handle(phone, text="", media=(), lat=None, lng=None):
    """Traite un message WhatsApp recu. media : [(octets, type)]. Retourne la liste des reponses."""
    db = get_db()
    phone = WA.phone_from(phone)
    user = wa_user(db, phone)
    kind = "position" if lat is not None else ("media" if media else "texte")
    wa_log(db, "in", phone, kind, text or (f"{lat},{lng}" if lat is not None else ", ".join(c for _r, c in media)), user)
    replies = []

    def done():
        for r in replies:
            wa_log(db, "out", phone, "texte", r, user, sess.get("project_id") if user else None)
        db.commit()
        return replies

    sess = {}
    if user is None:
        replies.append(WA.say("fr", "inconnu"))
        return done()
    lang = user["lang"] or "fr"
    sess = wa_session(db, phone)
    sess["user_id"] = user["id"]
    projects = wa_projects(db, user)
    if not projects:
        replies.append(WA.say(lang, "pas_chef"))
        wa_save_session(db, sess)
        return done()
    ids = [p["id"] for p in projects]
    if sess["project_id"] not in ids:
        sess["project_id"] = ids[0] if len(ids) == 1 else None
    p = next((x for x in projects if x["id"] == sess["project_id"]), None)
    listing = "\n".join(f"{i}. {x['name']}" for i, x in enumerate(projects, 1))
    if lat is not None:
        sess["loc_lat"], sess["loc_lng"], sess["loc_at"] = lat, lng, now_iso()
        if p:
            d, limit, _parcel = site_distance(p, lat, lng)
            replies.append(WA.say(lang, "position_ok" if d <= limit else "position_loin", d=d, r=limit))
            replies += wa_flush_pending(db, user, p, sess)
        else:
            replies.append(WA.say(lang, "choisir", liste=listing))
            sess["awaiting"] = "choix"
    for raw, ctype in media:
        ctype = (ctype or "").lower()
        if ctype.startswith("image/"):
            if p and wa_location_fresh(sess):
                replies.append(wa_send_photo(db, user, p, raw, sess))
            else:
                os.makedirs(WA_PENDING_DIR, exist_ok=True)
                pend = json.loads(sess["pending"] or "[]")[-(WA.PENDING_MAX - 1):]
                name = f"{secrets.token_hex(10)}.jpg"
                with open(os.path.join(WA_PENDING_DIR, name), "wb") as fh:
                    fh.write(raw)
                pend.append({"file": name, "at": now_iso(), "project_id": p["id"] if p else None})
                sess["pending"] = json.dumps(pend)
                if p:
                    if not any("minutes" in r for r in replies):
                        replies.append(WA.say(lang, "attente_position", m=WA.LOCATION_MINUTES))
                else:
                    sess["awaiting"] = "choix"
                    replies.append(WA.say(lang, "choisir", liste=listing))
        elif ctype.startswith("audio/"):
            if p:
                wa_add_note(db, user, p, "vocal", raw=raw, ctype=ctype)
                replies.append(WA.say(lang, "vocal_ok", resume=""))
            else:
                sess["awaiting"] = "choix"
                replies.append(WA.say(lang, "choisir", liste=listing))
        elif ctype.startswith("video/"):
            replies.append(WA.say(lang, "video"))
        else:
            replies.append(WA.say(lang, "media_erreur"))
    if text and not media and lat is None:
        cmd, arg = WA.command(text)
        if cmd == "numero" and sess["awaiting"] == "choix" and 1 <= arg <= len(projects):
            p = projects[arg - 1]
            sess["project_id"], sess["awaiting"] = p["id"], None
            pend = [dict(x, project_id=p["id"]) for x in json.loads(sess["pending"] or "[]")]
            sess["pending"] = json.dumps(pend) if pend else None
            replies.append(WA.say(lang, "choisi", chantier=p["name"]))
            if pend and wa_location_fresh(sess):
                replies += wa_flush_pending(db, user, p, sess)
            elif pend:
                replies.append(WA.say(lang, "attente_position", m=WA.LOCATION_MINUTES))
        elif cmd == "chantiers":
            sess["awaiting"] = "choix"
            replies.append(WA.say(lang, "choisir", liste=listing))
        elif p is None:
            sess["awaiting"] = "choix"
            replies.append(WA.say(lang, "choisir", liste=listing))
        elif cmd == "aide":
            replies.append(WA.say(lang, "aide", chantier=p["name"]))
        elif cmd == "etape":
            st = project_stats(p["id"])["current"]
            if st is None:
                replies.append(WA.say(lang, "pas_etape"))
            else:
                n = db.execute("SELECT COUNT(*) FROM proofs WHERE step_id = ? AND ok = 1", (st["id"],)).fetchone()[0]
                replies.append(WA.say(lang, "etape", chantier=p["name"], etape=I18N.render(st["name"], lang),
                                      statut=I18N.translate(STATUS_LABELS.get(st["status"], st["status"]), lang), n=n, montant=fcfa_txt(st["amount"])))
        elif cmd == "termine":
            st = project_stats(p["id"])["current"]
            if st is None or st["status"] != "en_cours":
                replies.append(WA.say(lang, "pas_etape"))
            else:
                sess["awaiting"] = f"declarer:{st['id']}"
                replies.append(WA.say(lang, "termine_confirmer", etape=I18N.render(st["name"], lang)))
        elif cmd == "oui" and (sess["awaiting"] or "").startswith("declarer:"):
            sid = int(sess["awaiting"].split(":")[1])
            sess["awaiting"] = None
            msgs = as_user(user, declare_step, project_id=p["id"], step_id=sid)
            replies.append(" ".join(m for _c, m in msgs) or WA.say(lang, "annule"))
        elif cmd in ("oui", "non"):
            replies.append(WA.say(lang, "annule") if sess["awaiting"] else WA.say(lang, "rien_a_confirmer"))
            sess["awaiting"] = None
        elif cmd == "paiements":
            rows = db.execute("SELECT * FROM payment_records WHERE payee_id = ? AND status = 'declare' ORDER BY id", (user["id"],)).fetchall()
            if not rows:
                replies.append(WA.say(lang, "paiements_aucun"))
            else:
                lines = []
                for r in rows:
                    due = payment_due(db, r["kind"], r["ref_id"])
                    lines.append(f"{r['id']} : {fcfa_txt(r['amount'])} FCFA – {due['label'] if due else ''}"
                                 + (f" (réf. {r['reference']})" if r["reference"] else ""))
                replies.append(WA.say(lang, "paiements", liste="\n".join(lines)))
        elif cmd in ("recu", "probleme"):
            rid = arg if cmd == "recu" else arg[0]
            r = db.execute("SELECT * FROM payment_records WHERE id = ? AND payee_id = ? AND status = 'declare'", (rid, user["id"])).fetchone()
            if r is None:
                replies.append(WA.say(lang, "paiement_inconnu", n=rid))
            else:
                form = {"action": "confirm"} if cmd == "recu" else {"action": "contest", "text": arg[1]}
                msgs = as_user(user, payment_answer, form=form, rid=rid)
                replies.append(" ".join(m for _c, m in msgs))
        else:
            wa_add_note(db, user, p, "texte", text=text.strip()[:2000])
            replies.append(WA.say(lang, "note_ok"))
    if not replies and p:
        replies.append(WA.say(lang, "aide", chantier=p["name"]))
    wa_save_session(db, sess)
    return done()


@app.route("/whatsapp/entrant", methods=["POST"])
def whatsapp_incoming():
    """Webhook Twilio : un message WhatsApp arrive."""
    if not WA.configured():
        abort(404)
    url = env("TWILIO_WEBHOOK_URL") or request.url
    if not WA.valid_signature(url, request.form.to_dict(), request.headers.get("X-Twilio-Signature", "")):
        abort(403)
    f = request.form
    media = []
    for i in range(min(to_int(f.get("NumMedia")), 5)):
        try:
            raw, ctype = WA.fetch_media(f.get(f"MediaUrl{i}"))
            media.append((raw, f.get(f"MediaContentType{i}") or ctype))
        except Exception:
            media.append((b"", "erreur/inconnu"))
    lat, lng = to_float(f.get("Latitude")), to_float(f.get("Longitude"))
    replies = wa_handle(f.get("From", ""), f.get("Body", ""), media, lat, lng)
    return app.response_class(WA.twiml(replies), mimetype="application/xml")


@app.route("/whatsapp/simulateur", methods=["GET", "POST"])
@login_required
def whatsapp_simulator():
    """Simulateur du fil WhatsApp : memes regles que le vrai webhook, sans Twilio."""
    me = current_user()
    is_admin_sim = can("platform")
    if WA.configured() and not is_admin_sim:
        abort(404)
    if not is_admin_sim and me["role"] != "chef":
        abort(403)
    phone = NOTIFY.e164(me["phone"]) if me["phone"] else None
    if is_admin_sim and request.values.get("phone"):
        phone = NOTIFY.e164(request.values.get("phone"))
    if request.method == "POST":
        if not phone:
            flash(_("Ajoutez d'abord votre numéro de téléphone dans votre compte."), "error")
            return redirect(url_for("account"))
        media = []
        for field in ("photo", "audio"):
            fl = request.files.get(field)
            if fl and fl.filename:
                media.append((fl.read(), fl.mimetype or ("image/jpeg" if field == "photo" else "audio/ogg")))
        lat = to_float(request.form.get("lat")) if request.form.get("share") == "1" else None
        lng = to_float(request.form.get("lng")) if lat is not None else None
        wa_handle(phone, request.form.get("text", "").strip(), media, lat, lng)
        return redirect(url_for("whatsapp_simulator", phone=phone if is_admin_sim else None))
    msgs = get_db().execute("SELECT * FROM wa_messages WHERE phone = ? ORDER BY id DESC LIMIT 60", (phone or "",)).fetchall()[::-1]
    projects = wa_projects(get_db(), me) if me["role"] == "chef" else []
    return render_template("whatsapp_sim.html", msgs=msgs, phone=phone, admin_sim=is_admin_sim, projects=projects,
                           configured=WA.configured(), number=WA.display_number())


@app.route("/chantiers/<int:project_id>/notes")
@login_required
def site_notes_page(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    db = get_db()
    notes = db.execute("SELECT n.*, u.name AS author, st.name AS step_name FROM site_notes n JOIN users u ON u.id = n.user_id "
                       "LEFT JOIN steps st ON st.id = n.step_id WHERE n.project_id = ? ORDER BY n.id DESC LIMIT 200",
                       (project_id,)).fetchall()
    if g.project_role == "owner":
        db.execute("UPDATE site_notes SET read_at = ? WHERE project_id = ? AND read_at IS NULL", (now_iso(), project_id))
        db.commit()
    cats = {k: VOICE.CATEGORY_LABEL[k].get(g.lang) or VOICE.CATEGORY_LABEL[k]["fr"] for k in VOICE.CATEGORY_LABEL}
    return render_template("site_notes.html", p=p, notes=notes, cats=cats, role=g.project_role,
                           can_transcribe=VOICE.can_transcribe(), wa_on=WA.configured())


@app.route("/notes/<int:nid>/audio")
@login_required
def site_note_audio(nid):
    n = get_db().execute("SELECT * FROM site_notes WHERE id = ?", (nid,)).fetchone()
    if n is None or not n["filename"]:
        abort(404)
    load_project(n["project_id"], roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    return send_from_directory(VOICE_DIR, n["filename"])


# --------------------------------------------------------------------------
# Plan de financement et dossier de credit
# --------------------------------------------------------------------------
def fin_access(project_id, write=False):
    """Proprietaire, co-proprietaire et responsable financier ; le comptable du chantier en lecture."""
    p = load_project(project_id, roles=("owner", "intervenant"))
    if g.project_role == "intervenant" and (write or not member_can("finances")):
        abort(403)
    return p


def fin_outflows(db, p):
    """Sorties du chantier : etapes (payees a leur date, sinon a leur fin prevue) et autres couts."""
    stats = project_stats(p["id"])
    sched = PRED.step_schedule(p, stats["steps"])
    out = []
    for st in stats["steps"]:
        paid = st["status"] in ("paye",)
        when = (st["paid_at"] or "")[:10] if paid and st["paid_at"] else (sched.get(st["id"]) or p["start_date"] or FIN.today_iso())
        out.append((str(when)[:10], st["amount"], I18N.render(st["name"]), paid))
    for c in db.execute("SELECT * FROM fin_costs WHERE project_id = ?", (p["id"],)):
        out.append((c["due_on"] or FIN.today_iso(), c["amount"], c["label"], bool(c["paid"])))
    return out


def fin_state(db, p):
    sources = db.execute("SELECT * FROM fin_sources WHERE project_id = ? ORDER BY COALESCE(expected_on, created_at), id",
                         (p["id"],)).fetchall()
    receipts = {}
    for r in db.execute("SELECT * FROM fin_receipts WHERE project_id = ? ORDER BY received_on", (p["id"],)):
        receipts.setdefault(r["source_id"], []).append((r["received_on"], r["amount"]))
    profile = db.execute("SELECT * FROM fin_profiles WHERE project_id = ?", (p["id"],)).fetchone()
    pl = FIN.plan(sources, receipts, fin_outflows(db, p))
    return sources, receipts, profile, pl, FIN.debt(profile, sources)


@app.route("/chantiers/<int:project_id>/financement", methods=["GET", "POST"])
@login_required
def financing(project_id):
    p = fin_access(project_id, write=request.method == "POST")
    db = get_db()
    me = current_user()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        back = redirect(url_for("financing", project_id=project_id, _anchor=f.get("anchor") or ""))
        if action == "source":
            kind = f.get("kind")
            amount = to_int(f.get("amount"))
            if kind not in FIN.KINDS or amount <= 0:
                flash(_("Choisissez le type de source et un montant."), "error")
                return back
            sid = to_int(f.get("source_id"), None)
            vals = (kind, f.get("label", "").strip()[:120] or None, f.get("lender", "").strip()[:120] or None, amount,
                    f.get("expected_on") or None, to_int(f.get("months"), None), to_float(f.get("rate")),
                    to_int(f.get("deferral_months"), None), to_int(f.get("monthly_payment"), None),
                    f.get("status") if f.get("status") in ("prevue", "confirmee") else "prevue", f.get("note", "").strip()[:500] or None)
            if sid and db.execute("SELECT 1 FROM fin_sources WHERE id = ? AND project_id = ?", (sid, project_id)).fetchone():
                db.execute("UPDATE fin_sources SET kind = ?, label = ?, lender = ?, amount = ?, expected_on = ?, months = ?, rate = ?, "
                           "deferral_months = ?, monthly_payment = ?, status = ?, note = ?, updated_at = ? WHERE id = ?",
                           vals + (now_iso(), sid))
            else:
                db.execute("INSERT INTO fin_sources (kind, label, lender, amount, expected_on, months, rate, deferral_months, "
                           "monthly_payment, status, note, project_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           vals + (project_id, now_iso()))
                log(project_id, L("Plan de financement : source ajoutée (%(k)s, %(a)s FCFA)", k=L(FIN.KINDS[kind]["fr"]), a=fcfa_txt(amount)))
        elif action == "delete_source":
            db.execute("DELETE FROM fin_receipts WHERE source_id = ? AND project_id = ?", (to_int(f.get("source_id")), project_id))
            db.execute("DELETE FROM fin_sources WHERE id = ? AND project_id = ?", (to_int(f.get("source_id")), project_id))
        elif action == "receipt":
            sid = to_int(f.get("source_id"))
            amount = to_int(f.get("amount"))
            if amount <= 0 or not db.execute("SELECT 1 FROM fin_sources WHERE id = ? AND project_id = ?", (sid, project_id)).fetchone():
                flash(_("Indiquez le montant reçu."), "error")
                return back
            db.execute("INSERT INTO fin_receipts (source_id, project_id, amount, received_on, note, created_by, created_at) "
                       "VALUES (?,?,?,?,?,?,?)", (sid, project_id, amount, f.get("received_on") or FIN.today_iso(),
                                                  f.get("note", "").strip()[:300] or None, me["id"], now_iso()))
            log(project_id, L("Plan de financement : %(a)s FCFA reçus", a=fcfa_txt(amount)))
        elif action == "delete_receipt":
            db.execute("DELETE FROM fin_receipts WHERE id = ? AND project_id = ?", (to_int(f.get("receipt_id")), project_id))
        elif action == "cost":
            amount = to_int(f.get("amount"))
            label = f.get("label", "").strip()[:120]
            if amount <= 0 or not label:
                flash(_("Indiquez le libellé et le montant."), "error")
                return back
            db.execute("INSERT INTO fin_costs (project_id, label, amount, due_on, paid, created_at) VALUES (?,?,?,?,?,?)",
                       (project_id, label, amount, f.get("due_on") or None, 1 if f.get("paid") else 0, now_iso()))
        elif action == "cost_paid":
            db.execute("UPDATE fin_costs SET paid = 1 - paid WHERE id = ? AND project_id = ?", (to_int(f.get("cost_id")), project_id))
        elif action == "delete_cost":
            db.execute("DELETE FROM fin_costs WHERE id = ? AND project_id = ?", (to_int(f.get("cost_id")), project_id))
        elif action == "profile":
            cur = f.get("income_currency") if f.get("income_currency") in FIN.CURRENCIES else "XOF"
            vals = (to_float(f.get("monthly_income")), cur, to_float(f.get("fx_rate")), to_float(f.get("other_charges")),
                    f.get("employer", "").strip()[:120] or None, f.get("country", "").strip()[:60] or None,
                    1 if f.get("diaspora") else 0, now_iso())
            if db.execute("SELECT 1 FROM fin_profiles WHERE project_id = ?", (project_id,)).fetchone():
                db.execute("UPDATE fin_profiles SET monthly_income = ?, income_currency = ?, fx_rate = ?, other_charges = ?, "
                           "employer = ?, country = ?, diaspora = ?, updated_at = ? WHERE project_id = ?", vals + (project_id,))
            else:
                db.execute("INSERT INTO fin_profiles (monthly_income, income_currency, fx_rate, other_charges, employer, country, "
                           "diaspora, updated_at, project_id) VALUES (?,?,?,?,?,?,?,?,?)", vals + (project_id,))
        else:
            abort(400)
        db.commit()
        flash(_("Enregistré."), "ok")
        return back
    sources, receipts, profile, pl, dbt = fin_state(db, p)
    rec_rows = {}
    for r in db.execute("SELECT * FROM fin_receipts WHERE project_id = ? ORDER BY received_on DESC", (project_id,)):
        rec_rows.setdefault(r["source_id"], []).append(r)
    costs = db.execute("SELECT * FROM fin_costs WHERE project_id = ? ORDER BY due_on", (project_id,)).fetchall()
    peak = max([abs(m["in"]) for m in pl["months"]] + [abs(m["out"]) for m in pl["months"]] + [1])
    lang = g.lang
    return render_template("financing.html", p=p, pl=pl, sources=sources, rec_rows=rec_rows, profile=profile, debt=dbt,
                           costs=costs, peak=peak, can_edit=g.project_role == "owner",
                           KINDS={k: FIN.label(v, lang) for k, v in FIN.KINDS.items()},
                           FSTATUS={k: FIN.label(v, lang) for k, v in FIN.STATUS.items()}, LOANS=FIN.LOAN_KINDS,
                           CURRENCIES=FIN.CURRENCIES, suggestions=[FIN.label(x, lang) for x in FIN.COST_SUGGESTIONS],
                           month_label=lambda k: FIN.month_label(k, lang), DEBT_REF=FIN.DEBT_REFERENCE, EUR=FIN.EUR_XOF,
                           today=FIN.today_iso())


def fin_auto(db, p, sources, profile):
    has = lambda cat: bool(db.execute("SELECT 1 FROM documents WHERE project_id = ? AND category = ?", (p["id"], cat)).fetchone())
    steps = db.execute("SELECT * FROM steps WHERE project_id = ?", (p["id"],)).fetchall()
    return {"permit": has("Permis de construire"), "plans": has("Plan"), "devis": has("Devis"),
            "budget": bool(steps), "planning": bool(steps and p["start_date"] and all(s["planned_days"] for s in steps)),
            "sources": bool(sources),
            "apport": any(s["kind"] in ("epargne", "vente", "famille", "tontine", "transferts") for s in sources)
            and bool(db.execute("SELECT 1 FROM fin_receipts r JOIN fin_sources s ON s.id = r.source_id WHERE s.project_id = ? "
                                "AND s.kind IN ('epargne', 'vente', 'famille', 'tontine', 'transferts')", (p["id"],)).fetchone()),
            "progress": bool(db.execute("SELECT 1 FROM proofs WHERE project_id = ? AND ok = 1", (p["id"],)).fetchone()),
            "has_other_charges": bool(profile and profile["other_charges"])}


@app.route("/chantiers/<int:project_id>/financement/dossier", methods=["GET", "POST"])
@login_required
def financing_file(project_id):
    p = fin_access(project_id, write=request.method == "POST")
    db = get_db()
    if request.method == "POST":
        if request.form.get("action") == "delete":
            d = db.execute("SELECT * FROM fin_documents WHERE id = ? AND project_id = ?", (to_int(request.form.get("doc_id")), project_id)).fetchone()
            if d:
                db.execute("DELETE FROM fin_documents WHERE id = ?", (d["id"],))
                try:
                    os.remove(os.path.join(FIN_DIR, d["filename"]))
                except OSError:
                    pass
                db.commit()
            return redirect(url_for("financing_file", project_id=project_id))
        kind = request.form.get("kind")
        file = request.files.get("file")
        if kind not in FIN.DOC_KINDS or not file or not file.filename or ext_of(file.filename) not in DOC_EXT:
            flash(_('Choisissez un fichier (PDF, Word, Excel, image, DWG, ZIP).'), "error")
            return redirect(url_for("financing_file", project_id=project_id))
        raw = file.read()
        os.makedirs(FIN_DIR, exist_ok=True)
        name = f"{secrets.token_hex(12)}.{ext_of(file.filename)}"
        with open(os.path.join(FIN_DIR, name), "wb") as fh:
            fh.write(raw)
        db.execute("INSERT INTO fin_documents (project_id, user_id, kind, title, filename, original_name, sha256, size, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (project_id, current_user()["id"], kind, request.form.get("title", "").strip()[:150] or None,
                                                  name, file.filename[:150], hashlib.sha256(raw).hexdigest(), len(raw), now_iso()))
        db.commit()
        flash(_("Pièce ajoutée au dossier."), "ok")
        return redirect(url_for("financing_file", project_id=project_id, _anchor="pieces"))
    sources, receipts, profile, pl, dbt = fin_state(db, p)
    docs = db.execute("SELECT * FROM fin_documents WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    by_kind = {}
    for d in docs:
        by_kind.setdefault(d["kind"], []).append(d)
    diaspora = bool(profile and (profile["diaspora"] or profile["income_currency"] != "XOF"))
    items = FIN.checklist(g.lang, by_kind, fin_auto(db, p, sources, profile), diaspora)
    missing = [i for i in items if i["required"] and not i["ok"]]
    stats = project_stats(project_id)
    owner = db.execute("SELECT * FROM users WHERE id = ?", (p["owner_id"],)).fetchone()
    lang = g.lang
    return render_template("financing_file.html", p=p, pl=pl, debt=dbt, profile=profile, items=items, missing=missing,
                           sections=FIN.sections(items),
                           s=stats, owner=owner, sources=sources, schedule=PRED.step_schedule(p, stats["steps"]),
                           can_edit=g.project_role == "owner", DOC_KINDS={k: FIN.label(v, lang) for k, v in FIN.DOC_KINDS.items()},
                           KINDS={k: FIN.label(v, lang) for k, v in FIN.KINDS.items()},
                           FSTATUS={k: FIN.label(v, lang) for k, v in FIN.STATUS.items()},
                           month_label=lambda k: FIN.month_label(k, lang), DEBT_REF=FIN.DEBT_REFERENCE,
                           docs_project=db.execute("SELECT category, title, created_at FROM documents WHERE project_id = ? "
                                                   "AND category IN ('Plan', 'Devis', 'Permis de construire') ORDER BY id",
                                                   (project_id,)).fetchall(),
                           today=FIN.today_iso())


@app.route("/financement/pieces/<int:doc_id>")
@login_required
def financing_doc(doc_id):
    d = get_db().execute("SELECT * FROM fin_documents WHERE id = ?", (doc_id,)).fetchone()
    if d is None:
        abort(404)
    fin_access(d["project_id"])
    return send_from_directory(FIN_DIR, d["filename"], as_attachment=False, download_name=d["original_name"] or d["filename"])


def finance_daily(db):
    """Alerte le proprietaire quand un manque de financement approche ou qu'une source est en retard (une fois par mois)."""
    n = 0
    month = FIN.today_iso()[:7]
    for p in db.execute("SELECT * FROM projects p WHERE EXISTS (SELECT 1 FROM fin_sources s WHERE s.project_id = p.id)").fetchall():
        sources = db.execute("SELECT * FROM fin_sources WHERE project_id = ?", (p["id"],)).fetchall()
        receipts = {}
        for r in db.execute("SELECT * FROM fin_receipts WHERE project_id = ?", (p["id"],)):
            receipts.setdefault(r["source_id"], []).append((r["received_on"], r["amount"]))
        pl = FIN.plan(sources, receipts, fin_outflows(db, p))
        gap = pl["first_gap"]
        key = f"{month}:{gap['month'] if gap else ''}:{len(pl['late'])}"
        prof = db.execute("SELECT alert_key FROM fin_profiles WHERE project_id = ?", (p["id"],)).fetchone()
        if prof and prof["alert_key"] == key:
            continue
        soon = gap and gap["month"] <= FIN.add_month(month, 2)
        if not soon and not pl["late"]:
            continue
        lang = (db.execute("SELECT lang FROM users WHERE id = ?", (p["owner_id"],)).fetchone()["lang"]) or "fr"
        if soon:
            notify(p["id"], owners_of(p, db), L("Financement : argent manquant"),
                   L("Il manquera %(a)s FCFA en %(m)s pour payer les étapes prévues. Ajoutez une source ou décalez des travaux.",
                     a=fcfa_txt(-gap["balance"]), m=FIN.month_label(gap["month"], lang)),
                   f"/chantiers/{p['id']}/financement", important=True, db=db)
        for s_, amount in pl["late"][:3]:
            notify(p["id"], owners_of(p, db), L("Financement : source en retard"),
                   L("%(k)s : %(a)s FCFA attendus ne sont pas encore reçus.", k=s_["label"] or L(FIN.KINDS[s_["kind"]]["fr"]),
                     a=fcfa_txt(amount)), f"/chantiers/{p['id']}/financement", db=db)
        if prof:
            db.execute("UPDATE fin_profiles SET alert_key = ? WHERE project_id = ?", (key, p["id"]))
        else:
            db.execute("INSERT INTO fin_profiles (project_id, alert_key, updated_at) VALUES (?,?,?)", (p["id"], key, now_iso()))
        n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------
# Accompagnement foncier
# --------------------------------------------------------------------------
def land_row(db, project_id):
    r = db.execute("SELECT * FROM land_files WHERE project_id = ?", (project_id,)).fetchone()
    return dict(r) if r else {"project_id": project_id, "doc_type": None, "title_ref": None, "holder_name": None,
                              "seller_name": None, "area_declared": None, "bornes": None, "checks": None, "notes": None}


def land_view(db, p, lang):
    f = land_row(db, p["id"])
    done = json.loads(f["checks"] or "{}")
    docs = db.execute("SELECT * FROM fin_documents WHERE project_id = ? AND kind IN (%s) ORDER BY id" % ",".join("?" * len(LAND.DOC_KINDS)),
                      (p["id"], *LAND.DOC_KINDS)).fetchall()
    by_kind = {}
    for d in docs:
        by_kind.setdefault(d["kind"], []).append(d)
    for check_id, kind in LAND.CHECK_DOC.items():           # une piece jointe vaut verification faite
        if by_kind.get(kind) and check_id in ("copie",):
            done[check_id] = True
    flags = LAND.flags_for(f, {"lat": p["lat"], "lng": p["lng"]}, lang, done)
    level, _f = LAND.assess(f["doc_type"], done, flags) if f["doc_type"] else (None, [])
    poly = LAND.parse_bornes(f["bornes"])
    return f, done, docs, by_kind, flags, level, poly


@app.route("/chantiers/<int:project_id>/foncier", methods=["GET", "POST"])
@login_required
def land_page(project_id):
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    me = current_user()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        back = redirect(url_for("land_page", project_id=project_id, _anchor=f.get("anchor") or ""))
        cur = land_row(db, project_id)
        if action == "save":
            doc_type = f.get("doc_type") if f.get("doc_type") in LAND.DOCS else None
            vals = (doc_type, f.get("title_ref", "").strip()[:80] or None, f.get("holder_name", "").strip()[:120] or None,
                    f.get("seller_name", "").strip()[:120] or None, to_float(f.get("area_declared")),
                    f.get("bornes", "").strip()[:2000] or None, me["id"], now_iso())
            if db.execute("SELECT 1 FROM land_files WHERE project_id = ?", (project_id,)).fetchone():
                db.execute("UPDATE land_files SET doc_type = ?, title_ref = ?, holder_name = ?, seller_name = ?, area_declared = ?, "
                           "bornes = ?, updated_by = ?, updated_at = ? WHERE project_id = ?", vals + (project_id,))
            else:
                db.execute("INSERT INTO land_files (doc_type, title_ref, holder_name, seller_name, area_declared, bornes, updated_by, "
                           "updated_at, project_id) VALUES (?,?,?,?,?,?,?,?,?)", vals + (project_id,))
            if doc_type:
                db.execute("UPDATE projects SET land_title = COALESCE(land_title, ?), land_ref = COALESCE(land_ref, ?) WHERE id = ?",
                           (LAND.label(LAND.DOCS[doc_type][0], "fr"), vals[1], project_id))
        elif action == "check":
            done = json.loads(cur["checks"] or "{}")
            cid = f.get("check")
            if cid not in {c[0] for c in LAND.CHECKS}:
                abort(400)
            done[cid] = f.get("done") == "1"
            if db.execute("SELECT 1 FROM land_files WHERE project_id = ?", (project_id,)).fetchone():
                db.execute("UPDATE land_files SET checks = ?, updated_at = ? WHERE project_id = ?", (json.dumps(done), now_iso(), project_id))
            else:
                db.execute("INSERT INTO land_files (project_id, checks, updated_by, updated_at) VALUES (?,?,?,?)",
                           (project_id, json.dumps(done), me["id"], now_iso()))
        elif action == "upload":
            kind = f.get("kind")
            file = request.files.get("file")
            if kind not in LAND.DOC_KINDS or not file or not file.filename or ext_of(file.filename) not in DOC_EXT:
                flash(_('Choisissez un fichier (PDF, Word, Excel, image, DWG, ZIP).'), "error")
                return back
            raw = file.read()
            os.makedirs(FIN_DIR, exist_ok=True)
            name = f"{secrets.token_hex(12)}.{ext_of(file.filename)}"
            with open(os.path.join(FIN_DIR, name), "wb") as fh:
                fh.write(raw)
            db.execute("INSERT INTO fin_documents (project_id, user_id, kind, title, filename, original_name, sha256, size, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (project_id, me["id"], kind, None, name, file.filename[:150],
                                                      hashlib.sha256(raw).hexdigest(), len(raw), now_iso()))
        elif action == "delete_doc":
            d = db.execute("SELECT * FROM fin_documents WHERE id = ? AND project_id = ?", (to_int(f.get("doc_id")), project_id)).fetchone()
            if d:
                db.execute("DELETE FROM fin_documents WHERE id = ?", (d["id"],))
        elif action == "request":
            if db.execute("SELECT 1 FROM land_requests WHERE project_id = ? AND status != 'faite'", (project_id,)).fetchone():
                flash(_("Une demande est déjà en cours pour ce terrain."), "error")
                return back
            db.execute("INSERT INTO land_requests (project_id, user_id, message, status, created_at) VALUES (?,?,?,?,?)",
                       (project_id, me["id"], f.get("message", "").strip()[:1000] or None, "nouvelle", now_iso()))
            notify(project_id, admins(db, "verify"), L("Vérification foncière demandée"),
                   L("%(n)s demande une vérification du terrain du chantier %(p)s.", n=me["name"], p=p["name"]), "/admin#foncier",
                   important=True)
            log(project_id, L("Vérification foncière demandée"))
            flash(_("Demande envoyée : l'équipe ChantierVrai vous recontacte pour le devis du notaire ou du géomètre partenaire."), "ok")
        else:
            abort(400)
        db.commit()
        return back
    lang = g.lang
    f, done, docs, by_kind, flags, level, poly = land_view(db, p, lang)
    requests_ = db.execute("SELECT * FROM land_requests WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    checks = [{"id": c[0], "label": LAND.label(c[1], lang), "who": LAND.label(c[2], lang), "done": bool(done.get(c[0])),
               "doc": LAND.CHECK_DOC.get(c[0])} for c in (LAND.applicable(f["doc_type"]) if f["doc_type"] else LAND.CHECKS)]
    return render_template("land.html", p=p, f=f, checks=checks, docs=docs, by_kind=by_kind, flags=flags, level=level,
                           poly=poly, area=LAND.area_m2(poly), inside=LAND.inside(p["lat"], p["lng"], poly) if len(poly) >= 3 else None,
                           DOCS={k: (LAND.label(v[0], lang), LAND.label(v[1], lang)) for k, v in LAND.DOCS.items()},
                           RISK={k: LAND.label(v, lang) for k, v in LAND.RISK.items()},
                           DOC_LABELS={k: LAND.label(v, lang) for k, v in LAND.DOC_LABELS.items()}, requests=requests_)


def land_risk(db, p):
    f = land_row(db, p["id"])
    if not f["doc_type"]:
        return None
    return land_view(db, p, g.get("lang", "fr"))[5]


# --------------------------------------------------------------------------
# Comptage des livraisons
# --------------------------------------------------------------------------
def count_order(oid):
    """Compte les materiaux sur les photos verifiees de la commande (livraison et comptage)."""
    db = connect()
    try:
        o = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        lines = [ln for ln in db.execute("SELECT * FROM order_lines WHERE order_id = ?", (oid,)) if ln["material"] not in COUNT.VOLUME]
        photos = db.execute("SELECT * FROM proofs WHERE order_id = ? AND ok = 1 AND kind = 'photo' ORDER BY id DESC LIMIT 6", (oid,)).fetchall()
        if not lines or not photos:
            return
        images = []
        for ph in photos:
            try:
                images.append(Image.open(os.path.join(UPLOAD_DIR, ph["filename"])))
            except Exception:
                pass
        items = [{"id": str(ln["id"]), "nom": ln["name"], "unite": ln["unit"]} for ln in lines]
        res, remark = COUNT.count(images, items, "Livraison de matériaux sur un chantier de construction en Côte d'Ivoire.")
        db.execute("DELETE FROM delivery_counts WHERE order_id = ?", (oid,))
        for ln in lines:
            r = res.get(str(ln["id"]))
            if r:
                db.execute("INSERT INTO delivery_counts (order_id, line_id, ai_count, ai_conf, method, remark, photos, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (oid, ln["id"], r["compte"], r["confiance"], r["methode"], r["remarque"] or remark,
                                                        len(images), now_iso()))
        db.commit()
    except Exception as e:
        db.execute("DELETE FROM delivery_counts WHERE order_id = ?", (oid,))
        db.execute("INSERT INTO delivery_counts (order_id, line_id, remark, created_at) VALUES (?,?,?,?)",
                   (oid, 0, f"Comptage impossible : {str(e)[:200]}", now_iso()))
        db.commit()
    finally:
        db.close()


def order_counts(db, oid):
    return {r["line_id"]: r for r in db.execute("SELECT * FROM delivery_counts WHERE order_id = ?", (oid,))}


def count_gaps(db, oid, declared):
    """Lignes ou le chef declare autre chose que ce que l'IA a compte avec assez de confiance."""
    counts = order_counts(db, oid)
    gaps = []
    for ln in order_lines(oid, db):
        c = counts.get(ln["id"])
        q = declared.get(ln["id"])
        if c and c["ai_count"] is not None and q is not None and COUNT.compare(ln["qty"], q, c["ai_count"], c["ai_conf"]) == "a_verifier":
            gaps.append((ln, q, c["ai_count"]))
    return gaps


@app.route("/commandes/<int:oid>/comptage", methods=["POST"])
@login_required
def order_count_photo(oid):
    o, p = get_order(oid)
    if g.order_role not in ("chef", "owner") or o["status"] not in ("livree", "litige"):
        abort(403)
    db = get_db()
    step = db.execute("SELECT * FROM steps WHERE id = ?", (o["step_id"],)).fetchone()
    ok, reasons = process_proof(p, step, current_user(), source="chef", order_id=oid)
    if ok is None:
        flash(reasons, "error")
    elif ok:
        pid_ = g.get("last_proof_id")
        db.execute("UPDATE proofs SET note = ? WHERE id = ? AND (note IS NULL OR note = '')", ("Photo de comptage", pid_))
        db.commit()
        if COUNT.ai_enabled():
            run_async(count_order, oid)
        flash(_("Photo de comptage vérifiée.") + (" " + _("Le comptage sur la photo apparaît dans une minute.") if COUNT.ai_enabled() else ""), "ok")
    else:
        flash(_("Photo refusée : ") + "; ".join(map(I18N.render, reasons)), "error")
    return redirect(url_for("order", oid=oid, _anchor="comptage"))


# --------------------------------------------------------------------------
# Plan et realite : compter sur place ce que prevoit le plan
# --------------------------------------------------------------------------
PLAN_EDITORS = ("architecte", "ingenieur", "conducteur", "controleur")


def plan_can_edit(role):
    return role in ("owner", "inspecteur", "admin") or (role == "intervenant" and g.get("member_role") in PLAN_EDITORS)


def plan_can_count(role):
    return role in ("chef", "inspecteur") or (role == "intervenant" and g.get("member_role") == "conducteur")


def plan_status(it):
    return COUNT.compare(it["expected"], it["declared"], it["ai_count"], it["ai_conf"])


def count_plan_item(item_id):
    db = connect()
    try:
        it = db.execute("SELECT * FROM plan_items WHERE id = ?", (item_id,)).fetchone()
        photos = db.execute("SELECT pr.* FROM plan_item_photos x JOIN proofs pr ON pr.id = x.proof_id WHERE x.item_id = ? AND pr.ok = 1 "
                            "ORDER BY pr.id DESC LIMIT 6", (item_id,)).fetchall()
        images = [Image.open(os.path.join(UPLOAD_DIR, ph["filename"])) for ph in photos]
        if not images:
            return
        res, remark = COUNT.count(images, [{"id": "x", "nom": I18N.render(it["label"], "fr"), "unite": "unités"}],
                                  "Contrôle d'un bâtiment en construction : on compare ce qui est construit à ce que prévoit le plan."
                                  + (f" Niveau ou zone : {it['level']}." if it["level"] else ""))
        r = res.get("x") or {}
        db.execute("UPDATE plan_items SET ai_count = ?, ai_conf = ?, ai_note = ?, updated_at = ? WHERE id = ?",
                   (r.get("compte"), r.get("confiance"), (r.get("methode") or "") + (" — " + r["remarque"] if r.get("remarque") else ""),
                    now_iso(), item_id))
        it = db.execute("SELECT * FROM plan_items WHERE id = ?", (item_id,)).fetchone()
        db.execute("UPDATE plan_items SET status = ? WHERE id = ?", (plan_status(it), item_id))
        db.commit()
    except Exception as e:
        db.execute("UPDATE plan_items SET ai_note = ? WHERE id = ?", (f"Comptage impossible : {str(e)[:200]}", item_id))
        db.commit()
    finally:
        db.close()


@app.route("/chantiers/<int:project_id>/plan-reel", methods=["GET", "POST"])
@login_required
def plan_real(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant", "admin"))
    role = g.project_role
    db = get_db()
    me = current_user()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        back = redirect(url_for("plan_real", project_id=project_id, _anchor=f.get("anchor") or ""))
        if action in ("add", "from_plan", "delete") and not plan_can_edit(role):
            abort(403)
        if action == "add":
            label, expected = f.get("label", "").strip()[:100], to_float(f.get("expected"))
            if not label or expected is None or expected < 0:
                flash(_("Indiquez l'élément et le nombre prévu au plan."), "error")
                return back
            db.execute("INSERT INTO plan_items (project_id, label, expected, level, source, status, created_by, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (project_id, label, expected, f.get("level", "").strip()[:60] or None, "manuel",
                                                    "a_faire", me["id"], now_iso()))
        elif action == "from_plan":
            rd = db.execute("SELECT * FROM plan_readings WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
            if rd is None:
                flash(_("Aucun plan lu pour ce chantier : lisez d'abord un plan avec l'IA, ou ajoutez les éléments à la main."), "error")
                return back
            res = json.loads(rd["result"])
            added = 0
            for label, n in ((L("Fenêtres"), res.get("windows")), (L("Portes"), res.get("doors")),
                             (L("Pièces"), len(res.get("rooms") or []) or None)):
                if n:
                    stored = I18N.store(label)
                    if not db.execute("SELECT 1 FROM plan_items WHERE project_id = ? AND label = ? AND reading_id = ?",
                                      (project_id, stored, rd["id"])).fetchone():
                        db.execute("INSERT INTO plan_items (project_id, label, expected, source, reading_id, status, created_by, created_at) "
                                   "VALUES (?,?,?,?,?,?,?,?)", (project_id, stored, n, "plan_ia", rd["id"], "a_faire", me["id"], now_iso()))
                        added += 1
            flash(_("%(n)s élément(s) ajouté(s) depuis la lecture du plan. Vérifiez les nombres : l'IA peut se tromper.", n=added), "ok")
        elif action == "delete":
            db.execute("DELETE FROM plan_items WHERE id = ? AND project_id = ?", (to_int(f.get("item_id")), project_id))
        elif action == "declare":
            if not plan_can_count(role):
                abort(403)
            it = db.execute("SELECT * FROM plan_items WHERE id = ? AND project_id = ?", (to_int(f.get("item_id")), project_id)).fetchone()
            n = to_float(f.get("count"))
            if it is None or n is None or n < 0:
                flash(_("Indiquez le nombre compté sur place."), "error")
                return back
            db.execute("UPDATE plan_items SET declared = ?, declared_by = ?, note = ?, updated_at = ? WHERE id = ?",
                       (n, me["id"], f.get("note", "").strip()[:300] or None, now_iso(), it["id"]))
            it = db.execute("SELECT * FROM plan_items WHERE id = ?", (it["id"],)).fetchone()
            st = plan_status(it)
            db.execute("UPDATE plan_items SET status = ? WHERE id = ?", (st, it["id"]))
            if st in ("ecart", "a_verifier"):
                notify(project_id, owners_of(p), L("Écart avec le plan"),
                       L("%(l)s : %(d)s compté(s) sur place pour %(e)s prévu(s) au plan.", l=I18N.render(it["label"]), d=fmt_qty(n),
                         e=fmt_qty(it["expected"])), url_for("plan_real", project_id=project_id), important=True)
        else:
            abort(400)
        db.commit()
        return back
    items = db.execute("SELECT * FROM plan_items WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    photos = {}
    for x in db.execute("SELECT x.item_id, pr.id, pr.ok FROM plan_item_photos x JOIN proofs pr ON pr.id = x.proof_id "
                        "WHERE pr.project_id = ? ORDER BY pr.id", (project_id,)):
        photos.setdefault(x["item_id"], []).append(x)
    reading = db.execute("SELECT id, created_at FROM plan_readings WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    ctx = dict(p=p, role=role, items=items, photos=photos, reading=reading, can_edit=plan_can_edit(role),
               can_count=plan_can_count(role), ai_on=COUNT.ai_enabled(), zones=project_zones(db, project_id))
    if ctx["can_count"]:
        ctx["capture_token"] = new_capture_token(db, project_id)
    return render_template("plan_real.html", **ctx)


@app.route("/chantiers/<int:project_id>/plan-reel/photo", methods=["POST"])
@login_required
def plan_real_photo(project_id):
    p = load_project(project_id, roles=("chef", "inspecteur", "intervenant"))
    if not plan_can_count(g.project_role):
        abort(403)
    db = get_db()
    it = db.execute("SELECT * FROM plan_items WHERE id = ? AND project_id = ?", (to_int(request.form.get("item_id")), project_id)).fetchone()
    if it is None:
        flash(_("Choisissez l'élément photographié."), "error")
        return redirect(url_for("plan_real", project_id=project_id))
    st = project_stats(project_id)["current"] or db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position DESC LIMIT 1",
                                                            (project_id,)).fetchone()
    ok, reasons = process_proof(p, st, current_user(), source="chef" if g.project_role == "chef" else "inspecteur")
    if ok is None:
        flash(reasons, "error")
        return redirect(url_for("plan_real", project_id=project_id))
    pid_ = g.get("last_proof_id")
    db.execute("INSERT INTO plan_item_photos (item_id, proof_id, created_at) VALUES (?,?,?)", (it["id"], pid_, now_iso()))
    db.execute("UPDATE proofs SET note = ? WHERE id = ? AND (note IS NULL OR note = '')",
               ("Plan et réalité : " + I18N.render(it["label"], "fr"), pid_))
    db.commit()
    if ok and COUNT.ai_enabled():
        run_async(count_plan_item, it["id"])
    flash(_("Photo vérifiée et rattachée à l'élément.") if ok else _('Photo refusée : ') + "; ".join(map(I18N.render, reasons)),
          "ok" if ok else "error")
    return redirect(url_for("plan_real", project_id=project_id, _anchor=f"e{it['id']}"))


# --------------------------------------------------------------------------
# Guide d'utilisation
# --------------------------------------------------------------------------
@app.route("/aide")
@app.route("/aide/<slug>")
def help_page(slug=None):
    me = current_user()
    staff = bool(staff_role(me))
    if slug is None:
        slug = GUIDE.for_role(me["role"] if me else None)
    gd = GUIDE.guide(slug, g.lang, staff=staff)
    if gd is None:
        abort(404)
    shots = {s["img"] for s in gd["sections"]
             if s["img"] and os.path.exists(os.path.join(app.static_folder, "aide", s["img"] + ".png"))}
    return render_template("help.html", gd=gd, guides=GUIDE.catalog(g.lang, staff=staff), faq=GUIDE.faq(g.lang),
                           shots=shots)


# --------------------------------------------------------------------------
# Academie du BTP
# --------------------------------------------------------------------------
@app.route("/academie")
def academy():
    q = request.args.get("q", "").strip()[:300]
    hits, structural = ACAD.ask(q, g.lang) if q else ([], False)
    me = current_user()
    done = {}
    if me:
        for r in get_db().execute("SELECT course, MAX(score * 100 / total) AS best FROM academy_progress WHERE user_id = ? "
                                  "GROUP BY course", (me["id"],)):
            done[r["course"]] = r["best"]
    return render_template("academy.html", courses=ACAD.catalog(g.lang), q=q, hits=hits, structural=structural, done=done,
                           calcs=CALC.TYPES)


@app.route("/academie/<slug>", methods=["GET", "POST"])
def academy_course(slug):
    c = ACAD.course(slug, g.lang)
    if c is None:
        abort(404)
    result = None
    if request.method == "POST":
        answers = {i: to_int(request.form.get(f"q{i}"), None) for i in range(len(c["quiz"]))}
        score, total, details = ACAD.grade(slug, answers, g.lang)
        result = {"score": score, "total": total, "details": details}
        me = current_user()
        if me:
            db = get_db()
            db.execute("INSERT INTO academy_progress (user_id, course, score, total, done_at) VALUES (?,?,?,?,?)",
                       (me["id"], slug, score, total, now_iso()))
            db.commit()
    idx = [x["slug"] for x in ACAD.COURSES].index(slug)
    nxt = ACAD.course(ACAD.COURSES[(idx + 1) % len(ACAD.COURSES)]["slug"], g.lang)
    return render_template("academy_course.html", c=c, result=result, nxt=nxt,
                           calc_title=CALC.TYPES[c["calc"]]["title"] if c["calc"] else None)


# --------------------------------------------------------------------------
# Calculateur de materiaux et de dosages
# --------------------------------------------------------------------------
def calc_context(kind=None):
    kind = kind if kind in CALC.TYPES else "beton"
    values = {k: request.values.get(k, dflt) for k, _l, dflt, _o in CALC.TYPES[kind]["fields"]}
    result = CALC.compute(kind, values) if request.values.get("go") else None
    return dict(kind=kind, types=CALC.TYPES, values=values, result=result)


@app.route("/calculateur")
def calculator_public():
    return render_template("calculator.html", p=None, **calc_context(request.args.get("type")))


@app.route("/chantiers/<int:project_id>/calculateur", methods=["GET", "POST"])
@login_required
def calculator(project_id):
    p = load_project(project_id, roles=("owner", "chef"))
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    if request.method == "POST":
        kind = request.form.get("type")
        ctx = calc_context(kind)
        st = get_step(project_id, to_int(request.form.get("step_id")))
        if not ctx["result"] or not ctx["result"]["lines"]:
            flash(_("Rien à ajouter : vérifiez les dimensions."), "error")
            return redirect(url_for("calculator", project_id=project_id, type=kind))
        for mat, unit, q in ctx["result"]["lines"]:
            if mat == "Eau":
                continue
            row = db.execute("SELECT * FROM materials_plan WHERE step_id = ? AND material = ? AND COALESCE(unit, '') = ?",
                             (st["id"], mat, unit)).fetchone()
            if row:
                db.execute("UPDATE materials_plan SET qty_planned = COALESCE(qty_planned, 0) + ? WHERE id = ?", (q, row["id"]))
            else:
                db.execute("INSERT INTO materials_plan (project_id, step_id, material, unit, qty_planned) VALUES (?,?,?,?,?)",
                           (project_id, st["id"], mat, unit, q))
        log(project_id, L("Prévu des matériaux complété par le calculateur (%(t)s) pour « %(s)s »",
                          t=CALC.TYPES[ctx["kind"]]["title"], s=st["name"]))
        db.commit()
        flash(_("Quantités ajoutées au prévu de l'étape « %(s)s ». Elles servent au contrôle des factures et du stock.",
                s=st["name"]), "ok")
        return redirect(url_for("project_stock", project_id=project_id))
    current = project_stats(project_id)["current"]
    return render_template("calculator.html", p=p, steps=steps, current=current, role=g.project_role,
                           **calc_context(request.args.get("type")))


# --------------------------------------------------------------------------
# Stock du chantier : livre, utilise, disponible, et rapprochement avec les achats
# --------------------------------------------------------------------------
STOCK_KINDS = {"entree": "Livraison reçue", "sortie": "Consommation", "perte": "Perte ou casse",
               "inventaire": "Correction d'inventaire"}
STOCK_UNITS = {"Ciment": "sac", "Fer à béton": "barre", "Sable": "m³", "Gravier": "m³", "Parpaings": "unité",
               "Carreaux": "m²", "Peinture": "L"}


def stock_summary(db, project_id):
    """Par materiau : prevu, achete, livre, utilise, perdu, disponible, et les ecarts. Retourne (lignes, alertes)."""
    rows = {}

    def row(mat, unit=None):
        r = rows.setdefault(mat, {"material": mat, "unit": unit, "planned": 0.0, "bought": 0.0, "delivered": 0.0,
                                  "used": 0.0, "lost": 0.0, "adjust": 0.0, "min": None, "flags": []})
        if unit and not r["unit"]:
            r["unit"] = unit
        return r

    for pl in db.execute("SELECT material, unit, qty_planned FROM materials_plan WHERE project_id = ?", (project_id,)):
        row(pl["material"], pl["unit"])["planned"] += pl["qty_planned"] or 0
    for ln in db.execute("SELECT l.material, l.unit, l.qty FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id "
                         "WHERE i.project_id = ? AND i.status IN ('validee', 'a_verifier')", (project_id,)):
        row(ln["material"], ln["unit"])["bought"] += ln["qty"] or 0
    field = {"entree": "delivered", "sortie": "used", "perte": "lost", "inventaire": "adjust"}
    for m in db.execute("SELECT material, unit, kind, qty FROM stock_moves WHERE project_id = ?", (project_id,)):
        row(m["material"], m["unit"])[field[m["kind"]]] += m["qty"]
    for t in db.execute("SELECT material, min_qty FROM stock_thresholds WHERE project_id = ?", (project_id,)):
        row(t["material"])["min"] = t["min_qty"]
    alerts = []
    for r in rows.values():
        r["unit"] = r["unit"] or STOCK_UNITS.get(r["material"], "")
        r["available"] = round(r["delivered"] - r["used"] - r["lost"] + r["adjust"], 3)
        u = r["unit"]
        if r["bought"] > r["delivered"] * 1.05 + 0.01 and (r["delivered"] or r["used"]):
            r["flags"].append(_("Acheté mais pas livré : %(q)s %(u)s", q=fmt_qty(r["bought"] - r["delivered"]), u=u))
        if r["used"] > r["delivered"] + r["adjust"] + 0.001:
            r["flags"].append(_("Plus consommé que livré"))
        if r["planned"] and r["used"] > r["planned"] * MAT.OVER_QTY:
            r["flags"].append(_("Consommation au-dessus du prévu (%(pct)s %%)", pct=round(r["used"] * 100 / r["planned"])))
        if r["min"] is not None and r["available"] <= r["min"] and (r["delivered"] or r["used"]):
            r["flags"].append(_("Rupture de stock") if r["available"] <= 0 else _("Stock bas : à recommander"))
        for f in r["flags"]:
            alerts.append(f"{_(r['material'])} : {f}")
    table = sorted(rows.values(), key=lambda r: r["material"])
    return table, alerts


def fmt_qty(x):
    return f"{x:g}" if abs(x - round(x)) > 1e-9 else str(int(round(x)))


def stock_available(db, project_id, material):
    r = db.execute("SELECT COALESCE(SUM(CASE WHEN kind = 'entree' THEN qty WHEN kind = 'inventaire' THEN qty "
                   "ELSE -qty END), 0) FROM stock_moves WHERE project_id = ? AND material = ?",
                   (project_id, material)).fetchone()[0]
    return float(r or 0)


def add_stock_move(db, p, material, unit, qty, kind, user_id, step_id=None, source="manuel", order_id=None, note=None):
    db.execute("INSERT INTO stock_moves (project_id, step_id, material, unit, qty, kind, source, order_id, note, user_id, "
               "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (p["id"], step_id, material, unit, qty, kind, source, order_id, note, user_id, now_iso()))
    if kind in ("sortie", "perte", "inventaire"):
        th = db.execute("SELECT min_qty FROM stock_thresholds WHERE project_id = ? AND material = ?",
                        (p["id"], material)).fetchone()
        left = stock_available(db, p["id"], material)
        if th and left <= th["min_qty"] and left + (qty if kind != "inventaire" else -qty) > th["min_qty"]:
            notify(p["id"], owners_of(p, db) + [p["chef_id"]], L("Stock bas"),
                   L("%(m)s : il reste %(q)s %(u)s sur le chantier. Commandez avant la rupture.", m=material,
                     q=fmt_qty(left), u=unit or ""), f"/chantiers/{p['id']}/stock", important=True, db=db)


@app.route("/chantiers/<int:project_id>/stock", methods=["GET", "POST"])
@login_required
def project_stock(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "admin", "intervenant"))
    role = g.project_role
    if role == "intervenant" and not member_can("stock"):
        abort(403)
    if role == "intervenant" and g.get("member_role") == "conducteur":
        role = "chef"                    # le conducteur de travaux tient le stock comme le chef
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    if request.method == "POST":
        if role not in ("owner", "chef"):
            abort(403)
        f = request.form
        action = f.get("action")
        mat = MAT.normalize(f.get("material", ""))
        unit = (f.get("unit") or "").strip()[:20] or STOCK_UNITS.get(mat, "")
        q = to_float(f.get("qty"))
        back = redirect(url_for("project_stock", project_id=project_id))
        if action == "seuil":
            if q is None or q < 0:
                db.execute("DELETE FROM stock_thresholds WHERE project_id = ? AND material = ?", (project_id, mat))
            else:
                db.execute("INSERT INTO stock_thresholds (project_id, material, min_qty) VALUES (?,?,?) "
                           "ON CONFLICT (project_id, material) DO UPDATE SET min_qty = excluded.min_qty",
                           (project_id, mat, q))
            db.commit()
            flash(_("Seuil d'alerte enregistré."), "ok")
            return back
        if action not in STOCK_KINDS or q is None or (q <= 0 and action != "inventaire") or not f.get("material"):
            flash(_("Indiquez le matériau et une quantité."), "error")
            return back
        step_id = to_int(f.get("step_id"), None)
        if step_id:
            get_step(project_id, step_id)
        note = f.get("note", "").strip()[:200] or None
        if action == "inventaire":
            diff = round(q - stock_available(db, project_id, mat), 3)
            if abs(diff) < 1e-9:
                flash(_("Le stock compté correspond déjà au stock calculé."), "ok")
                return back
            add_stock_move(db, p, mat, unit, diff, "inventaire", current_user()["id"], step_id, note=note)
            log(project_id, L("Inventaire %(m)s : %(q)s %(u)s comptés (écart %(d)s)", m=mat, q=fmt_qty(q), u=unit,
                              d=("+" if diff > 0 else "") + fmt_qty(diff)))
            if diff < 0:
                emit_event(db, project_id, "anomalie", {"type": "inventaire", "materiau": mat, "manquant": -diff, "unite": unit})
                notify(project_id, owners_of(p), L("Écart d'inventaire"),
                       L("%(m)s : il manque %(d)s %(u)s par rapport au stock calculé.", m=mat, d=fmt_qty(-diff), u=unit),
                       url_for("project_stock", project_id=project_id), important=True)
        else:
            add_stock_move(db, p, mat, unit, q, action, current_user()["id"], step_id, note=note)
            log(project_id, L("%(k)s : %(q)s %(u)s de %(m)s", k=L(STOCK_KINDS[action]), q=fmt_qty(q), u=unit, m=mat))
        db.commit()
        flash(_("Mouvement enregistré."), "ok")
        return back
    table, alerts = stock_summary(db, project_id)
    moves = db.execute("SELECT m.*, u.name AS author, st.name AS step_name FROM stock_moves m JOIN users u ON u.id = m.user_id "
                       "LEFT JOIN steps st ON st.id = m.step_id WHERE m.project_id = ? ORDER BY m.id DESC LIMIT 60",
                       (project_id,)).fetchall()
    known = sorted({r["material"] for r in table} | set(MAT.CATALOG))
    return render_template("stock.html", p=p, role=role, table=table, alerts=alerts, moves=moves, steps=steps,
                           materials=known, units=STOCK_UNITS, KINDS=tr(STOCK_KINDS),
                           current=project_stats(project_id)["current"])


# --------------------------------------------------------------------------
# Controles techniques obligatoires avant validation
# --------------------------------------------------------------------------
# (mots de l'etape) -> [(controle, obligatoire, type, seuil, unite)]
CHECK_LIBRARY = [
    (("implantation", "terrassement", "fouille"),
     [("Implantation conforme au plan (axes et cotes)", 1, "visuel", None, None),
      ("Fond de fouille propre, à la bonne profondeur", 1, "visuel", None, None)]),
    (("fondation", "semelle", "soubassement"),
     [("Fond de fouille et béton de propreté contrôlés", 1, "visuel", None, None),
      ("Contrôle du ferraillage avant bétonnage (diamètres, espacements, enrobage)", 1, "visuel", None, None),
      ("Essai de résistance du béton (écrasement à 28 jours)", 0, "essai", 20, "MPa")]),
    (("poteau", "élévation", "elevation", "poutre", "chaînage", "chainage"),
     [("Contrôle du ferraillage (diamètres, espacements, enrobage)", 1, "visuel", None, None),
      ("Contrôle du coffrage (aplomb, étanchéité, étaiement)", 1, "visuel", None, None),
      ("Validation avant bétonnage", 1, "visuel", None, None)]),
    (("dalle", "plancher"),
     [("Contrôle du ferraillage de la dalle", 1, "visuel", None, None),
      ("Contrôle du coffrage et de l'étaiement", 1, "visuel", None, None),
      ("Validation avant bétonnage", 1, "visuel", None, None),
      ("Essai de résistance du béton (écrasement à 28 jours)", 0, "essai", 25, "MPa")]),
    (("maçonnerie", "maconnerie", "mur"),
     [("Qualité des parpaings (séchage, casse)", 0, "visuel", None, None),
      ("Aplomb et alignement des murs", 1, "visuel", None, None)]),
    (("toiture", "toit", "charpente", "couverture"),
     [("Contrôle de la charpente et des fixations", 1, "visuel", None, None),
      ("Étanchéité de la couverture", 0, "visuel", None, None)]),
    (("électricité", "electricite", "plomberie", "sanitaire", "réseaux", "reseaux"),
     [("Contrôle des installations électriques", 1, "visuel", None, None),
      ("Essai d'étanchéité des canalisations", 1, "visuel", None, None)]),
    (("finition", "carrelage", "peinture", "enduit", "menuiserie"),
     [("Contrôle des finitions", 0, "visuel", None, None)]),
    (("réception", "reception", "livraison"),
     [("Réception des travaux sans réserve", 1, "visuel", None, None)]),
]
CHECK_STATUS = {"a_faire": "À faire", "conforme": "Conforme", "non_conforme": "Non conforme"}


def checks_for_step(name):
    n = MAT.plain(name)
    found = []
    for words, checks in CHECK_LIBRARY:
        if any(MAT.plain(w) in n for w in words):
            found += [c for c in checks if c[0] not in [x[0] for x in found]]
    return found or [("Contrôle de conformité de l'étape", 0, "visuel", None, None)]


def seed_checks(db, project_id):
    """Cree les points de controle de la bibliotheque pour les etapes qui n'en ont pas encore."""
    changed = False
    for st in db.execute("SELECT * FROM steps WHERE project_id = ? AND checks_init = 0", (project_id,)).fetchall():
        if st["status"] in ("attente", "en_cours"):
            for name, req, kind, minv, unit in checks_for_step(st["name"]):
                db.execute("INSERT INTO step_checks (project_id, step_id, name, required, kind, min_value, unit, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (project_id, st["id"], I18N.store(L(name)), req, kind, minv, unit, now_iso()))
        db.execute("UPDATE steps SET checks_init = 1 WHERE id = ?", (st["id"],))
        changed = True
    if changed:
        db.commit()


def step_checks(db, step_id):
    return db.execute("SELECT c.*, u.name AS checker FROM step_checks c LEFT JOIN users u ON u.id = c.checked_by "
                      "WHERE c.step_id = ? ORDER BY c.id", (step_id,)).fetchall()


def blocking_checks(db, step_id):
    return [c for c in step_checks(db, step_id) if c["required"] and c["status"] != "conforme"]


def can_check(p, role=None):
    """Personne habilitee : inspecteur ou bureau de controle du chantier, ou administrateur."""
    role = role or project_role(p)
    return role in ("inspecteur", "admin")


def controllers_of(db, p):
    ids = [r[0] for r in db.execute("SELECT user_id FROM project_members WHERE project_id = ? AND role IN "
                                    "('controleur', 'ingenieur')", (p["id"],))]
    ids += [r[0] for r in db.execute("SELECT DISTINCT inspector_id FROM inspections WHERE project_id = ? AND "
                                     "status IN ('acceptee', 'realisee')", (p["id"],)) if r[0] not in ids]
    return ids


def finance_members(db, p):
    return [r[0] for r in db.execute("SELECT user_id FROM project_members WHERE project_id = ? AND role = 'finance'",
                                     (p["id"],))]


@app.route("/chantiers/<int:project_id>/etapes/<int:step_id>", methods=["GET"])
@login_required
def step_page(project_id, step_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "admin", "intervenant"))
    st = get_step(project_id, step_id)
    db = get_db()
    seed_checks(db, project_id)
    role = g.project_role
    checks = step_checks(db, step_id)
    return render_template("step.html", p=p, st=st, role=role, checks=checks, can_check=can_check(p, role),
                           verification=payment_verification(db, p, st), approvals=step_approvals(db, step_id),
                           finance=finance_members(db, p), controllers=controllers_of(db, p),
                           is_main_owner=current_user()["id"] == p["owner_id"],
                           CHECK_STATUS=tr(CHECK_STATUS), s=project_stats(project_id),
                           consumption=db.execute("SELECT material, unit, SUM(qty) AS q FROM stock_moves WHERE step_id = ? "
                                                  "AND kind = 'sortie' GROUP BY material, unit", (step_id,)).fetchall())


@app.route("/chantiers/<int:project_id>/etapes/<int:step_id>/controles", methods=["POST"])
@login_required
def step_checks_action(project_id, step_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "admin", "intervenant"))
    if g.project_role == "intervenant" and not (request.form.get("action") == "demander" and member_can("checks_request")):
        abort(403)
    st = get_step(project_id, step_id)
    db = get_db()
    role = g.project_role
    me = current_user()
    f = request.form
    action = f.get("action")
    back = redirect(url_for("step_page", project_id=project_id, step_id=step_id, _anchor="controles"))
    if action == "demander":
        ids = controllers_of(db, p)
        if not ids:
            flash(_("Aucun contrôleur habilité sur ce chantier. Le propriétaire peut réserver un inspecteur ou ajouter son bureau de contrôle."), "error")
            return back
        notify(project_id, ids, L("Contrôle demandé"),
               L("« %(s)s » : %(n)s contrôle(s) à faire sur le chantier %(p)s.", s=st["name"],
                 n=len([c for c in step_checks(db, step_id) if c["status"] == "a_faire"]), p=p["name"]),
               url_for("step_page", project_id=project_id, step_id=step_id), important=True)
        log(project_id, L("Contrôle demandé pour « %(s)s »", s=st["name"]))
        db.commit()
        flash(_("Les contrôleurs du chantier sont prévenus."), "ok")
        return back
    if action == "add":
        if role not in ("owner", "inspecteur", "admin"):
            abort(403)
        name = f.get("name", "").strip()[:200]
        if len(name) < 4:
            flash(_("Nommez le contrôle."), "error")
            return back
        kind = "essai" if f.get("kind") == "essai" else "visuel"
        db.execute("INSERT INTO step_checks (project_id, step_id, name, required, kind, min_value, unit, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?)", (project_id, step_id, name, 1 if f.get("required") else 0, kind,
                                                to_float(f.get("min_value")) if kind == "essai" else None,
                                                (f.get("unit") or "MPa")[:10] if kind == "essai" else None, now_iso()))
        log(project_id, L("Contrôle ajouté à « %(s)s » : %(c)s", s=st["name"], c=name))
        db.commit()
        return back
    c = db.execute("SELECT * FROM step_checks WHERE id = ? AND step_id = ?", (to_int(f.get("check_id")), step_id)).fetchone()
    if c is None:
        abort(404)
    cname = I18N.render(c["name"])
    if action == "result":
        if not can_check(p, role):
            flash(_("Seul un contrôleur habilité (inspecteur ou bureau de contrôle du chantier) peut valider un contrôle."), "error")
            return back
        note = f.get("note", "").strip()[:500] or None
        value = None
        if c["kind"] == "essai":
            value = to_float(f.get("value"))
            if value is None:
                flash(_("Indiquez le résultat de l'essai."), "error")
                return back
            status = "conforme" if c["min_value"] is None or value >= c["min_value"] else "non_conforme"
        else:
            status = f.get("status")
            if status not in ("conforme", "non_conforme"):
                abort(400)
        if status == "non_conforme" and not note and c["kind"] != "essai":
            flash(_("Expliquez la non-conformité pour que le chantier puisse corriger."), "error")
            return back
        doc_id = None
        file = request.files.get("file")
        if file and file.filename:
            if ext_of(file.filename) not in DOC_EXT:
                flash(_("Choisissez un fichier (PDF, Word, Excel, image, DWG, ZIP)."), "error")
                return back
            raw = file.read()
            name = f"{secrets.token_hex(12)}.{ext_of(file.filename)}"
            with open(os.path.join(DOC_DIR, name), "wb") as fh:
                fh.write(raw)
            doc_id = db.execute("INSERT INTO documents (project_id, user_id, category, title, filename, original_name, sha256, "
                                "size, is_public, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (project_id, me["id"], "Contrôle technique", f"{st['name']} – {cname}"[:150], name,
                                 file.filename[:150], hashlib.sha256(raw).hexdigest(), len(raw), 0, now_iso())).lastrowid
        db.execute("UPDATE step_checks SET status = ?, value = ?, note = ?, doc_id = COALESCE(?, doc_id), checked_by = ?, "
                   "checked_at = ? WHERE id = ?", (status, value, note, doc_id, me["id"], now_iso(), c["id"]))
        res = L("conforme") if status == "conforme" else L("non conforme")
        log(project_id, L("Contrôle « %(c)s » (%(s)s) : %(r)s", c=cname, s=st["name"], r=res)
            + (L(", %(v)s %(u)s", v=fmt_qty(value), u=c["unit"] or "") if value is not None else ""), db, me["id"])
        emit_event(db, project_id, "controle.resultat", {"etape_id": step_id, "etape": st["name"], "controle": cname,
                                                         "statut": status, "valeur": value, "unite": c["unit"], "note": note})
        if status == "non_conforme":
            emit_event(db, project_id, "anomalie", {"type": "non_conformite", "etape": st["name"], "controle": cname, "note": note})
        notify(project_id, owners_of(p, db) + [p["chef_id"]],
               L("Contrôle conforme") if status == "conforme" else L("Non-conformité relevée"),
               L("« %(s)s » : %(c)s", s=st["name"], c=cname) + (L(". %(n)s", n=note) if note else ""),
               url_for("step_page", project_id=project_id, step_id=step_id), important=status != "conforme", db=db)
        db.commit()
        flash(_("Résultat du contrôle enregistré."), "ok")
        return back
    if action == "optional":
        if me["id"] != p["owner_id"]:
            flash(_("Seul le propriétaire principal peut rendre un contrôle facultatif."), "error")
            return back
        db.execute("UPDATE step_checks SET required = 0, made_optional = 1 WHERE id = ?", (c["id"],))
        log(project_id, L("Contrôle « %(c)s » rendu facultatif par le propriétaire (« %(s)s »)", c=cname, s=st["name"]))
        notify(project_id, controllers_of(db, p), L("Contrôle rendu facultatif"),
               L("« %(s)s » : %(c)s", s=st["name"], c=cname), url_for("step_page", project_id=project_id, step_id=step_id), db=db)
        db.commit()
        flash(_("Contrôle rendu facultatif. Ce choix est noté dans l'historique et pèse sur l'indice de confiance."), "ok")
        return back
    if action == "required" and role == "owner":
        db.execute("UPDATE step_checks SET required = 1 WHERE id = ?", (c["id"],))
        db.commit()
        return back
    if action == "delete" and role in ("owner", "inspecteur") and c["status"] == "a_faire" and not c["required"]:
        db.execute("DELETE FROM step_checks WHERE id = ?", (c["id"],))
        log(project_id, L("Contrôle retiré de « %(s)s » : %(c)s", s=st["name"], c=cname))
        db.commit()
        return back
    flash(_("Action impossible."), "error")
    return back


# --------------------------------------------------------------------------
# Verification avant paiement, circuit de validation, situation des travaux
# --------------------------------------------------------------------------
def step_approvals(db, step_id):
    return db.execute("SELECT a.*, u.name FROM payment_approvals a JOIN users u ON u.id = a.user_id WHERE a.step_id = ? "
                      "ORDER BY a.id", (step_id,)).fetchall()


def payment_verification(db, p, st):
    """Les cinq verifications avant de payer une etape. Chaque point : (titre, etat ok/warn/bad, lignes)."""
    out = []
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (p["id"],)).fetchall()
    total = sum(x["amount"] for x in steps)
    paid = sum(x["amount"] for x in steps if x["status"] in ("paye", "versement"))
    contract = p["montant_marche"] or total
    lines = [_("Montant de l'étape : %(v)s FCFA", v=f"{st['amount']:,}".replace(",", " ")),
             _("Déjà payé : %(v)s FCFA sur %(t)s FCFA", v=f"{paid:,}".replace(",", " "), t=f"{contract:,}".replace(",", " "))]
    state = "ok"
    if paid + st["amount"] > contract:
        state = "bad"
        lines.append(_("Ce paiement dépasserait le montant du contrat."))
    out.append((_("1. Montant prévu au contrat"), state, lines))

    plans = db.execute("SELECT material, unit, SUM(qty_planned) AS q FROM materials_plan WHERE step_id = ? GROUP BY material, unit",
                       (st["id"],)).fetchall()
    used = {r["material"]: r["q"] for r in db.execute("SELECT material, SUM(qty) AS q FROM stock_moves WHERE step_id = ? "
                                                      "AND kind = 'sortie' GROUP BY material", (st["id"],))}
    bought = {r["material"]: r["q"] for r in db.execute("SELECT material, SUM(qty) AS q FROM invoice_lines WHERE step_id = ? "
                                                        "GROUP BY material", (st["id"],))}
    lines, state = [], "ok"
    for pl in plans:
        q_used, q_bought = used.get(pl["material"], 0) or 0, bought.get(pl["material"], 0) or 0
        q = q_used or q_bought
        pct = round(q * 100 / pl["q"]) if pl["q"] else None
        lines.append(_("%(m)s : %(q)s %(u)s prévus, %(b)s achetés, %(c)s utilisés", m=_(pl["material"]), q=fmt_qty(pl["q"] or 0),
                       u=pl["unit"] or "", b=fmt_qty(q_bought), c=fmt_qty(q_used)))
        if pct is not None and (pct < 60 or pct > MAT.OVER_QTY * 100):
            state = "warn"
    if not plans:
        state = "warn"
        lines.append(_("Aucune quantité prévue pour cette étape : utilisez le calculateur pour comparer."))
    out.append((_("2. Quantités déclarées"), state, lines))

    checks = step_checks(db, st["id"])
    missing = [c for c in checks if c["required"] and c["status"] != "conforme"]
    nc = [c for c in checks if c["status"] == "non_conforme"]
    insp = db.execute("SELECT verdict FROM inspections WHERE step_id = ? AND status = 'realisee' ORDER BY id DESC LIMIT 1",
                      (st["id"],)).fetchone()
    lines = [_("%(d)s contrôle(s) conforme(s) sur %(t)s", d=len([c for c in checks if c["status"] == "conforme"]), t=len(checks))]
    lines += [_("Manquant : %(c)s", c=I18N.render(c["name"])) for c in missing]
    lines += [_("Non conforme : %(c)s", c=I18N.render(c["name"])) for c in nc if not c["required"]]
    if insp:
        lines.append(_("Inspection indépendante : %(v)s", v=_(VERDICTS.get(insp["verdict"], insp["verdict"] or ""))))
    q_issues = q_open_issues(db, step_id=st["id"])
    q_last = db.execute("SELECT score FROM quality_reviews WHERE step_id = ? AND status = 'pret' ORDER BY id DESC LIMIT 1",
                        (st["id"],)).fetchone()
    if q_last and q_last["score"] is not None:
        lines.append(_("Contrôle qualité des photos : %(s)s/100", s=q_last["score"]))
    lines += [_("Problème probable non résolu : %(l)s", l=q_label(x["ouvrage"], x["point"], x["label"])) for x in q_issues]
    state = "bad" if missing else "warn" if nc or q_issues or (insp and insp["verdict"] != "conforme") else "ok"
    out.append((_("3. Travaux réellement contrôlés"), state, lines))

    proofs = db.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN ai_same_site = 0 OR ai_construction = 0 THEN 1 ELSE 0 END) AS doubt "
                        "FROM proofs WHERE step_id = ? AND ok = 1", (st["id"],)).fetchone()
    invs = db.execute("SELECT COUNT(*) FROM invoices WHERE step_id = ? AND status IN ('validee', 'a_verifier')",
                      (st["id"],)).fetchone()[0]
    docs = db.execute("SELECT COUNT(*) FROM step_checks WHERE step_id = ? AND doc_id IS NOT NULL", (st["id"],)).fetchone()[0]
    lines = [_("%(n)s preuve(s) photo vérifiée(s)", n=proofs["n"] or 0), _("%(n)s facture(s)", n=invs),
             _("%(n)s rapport(s) de contrôle", n=docs)]
    if proofs["doubt"]:
        lines.append(_("%(n)s photo(s) douteuse(s) selon l'IA", n=proofs["doubt"]))
    state = "bad" if not proofs["n"] else "warn" if proofs["doubt"] else "ok"
    out.append((_("4. Justificatifs disponibles"), state, lines))

    appr = step_approvals(db, st["id"])
    fin = finance_members(db, p)
    lines = [_("Déclarée terminée par le chef de chantier le %(d)s", d=format_d(st["declared_at"]))] if st["declared_at"] else \
        [_("Pas encore déclarée terminée par le chef de chantier.")]
    for a in appr:
        lines.append(_("Approuvée par %(n)s (%(l)s) le %(d)s", n=a["name"], l=_(APPROVAL_LEVELS.get(a["level"], a["level"])),
                       d=format_d(a["created_at"])))
    if fin:
        lines.append(_("Circuit à deux niveaux : maître d'ouvrage puis responsable financier."))
    state = "ok" if st["status"] in ("paye", "versement") else "warn"
    out.append((_("5. Validations nécessaires"), state, lines))
    return out


APPROVAL_LEVELS = {"ouvrage": "maître d'ouvrage", "finance": "responsable financier"}


@app.route("/chantiers/<int:project_id>/decompte")
@login_required
def decompte(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "admin", "intervenant"))
    if g.project_role == "intervenant" and not member_can("decompte"):
        abort(403)
    db = get_db()
    s = project_stats(project_id)
    seed_checks(db, project_id)
    rows = []
    for st in s["steps"]:
        checks = step_checks(db, st["id"])
        rows.append({"st": st, "checks_ok": len([c for c in checks if c["status"] == "conforme"]), "checks": len(checks),
                     "missing": len([c for c in checks if c["required"] and c["status"] != "conforme"]),
                     "orders": db.execute("SELECT COALESCE(SUM(received_total), 0) FROM orders WHERE step_id = ? AND "
                                          "status IN ('receptionnee', 'a_payer')", (st["id"],)).fetchone()[0]})
    paid = sum(r["st"]["amount"] for r in rows if r["st"]["status"] in ("paye", "versement"))
    to_pay = sum(r["st"]["amount"] for r in rows if r["st"]["status"] == "declare")
    contract = p["montant_marche"] or s["total"]
    return render_template("decompte.html", p=p, s=s, rows=rows, paid=paid, to_pay=to_pay, contract=contract,
                           materials=sum(r["orders"] for r in rows), today=now_iso(), role=g.project_role)


# --------------------------------------------------------------------------
# Indice de confiance du chantier
# --------------------------------------------------------------------------
def trust_inputs(db, p, s, pred):
    pid = p["id"]
    seed_checks(db, pid)
    plans = db.execute("SELECT * FROM materials_plan WHERE project_id = ?", (pid,)).fetchall()
    lines = db.execute("SELECT l.* FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id WHERE i.project_id = ?",
                       (pid,)).fetchall()
    _t, mat_alerts = MAT.compare(plans, lines, s["steps"])
    _st, stock_alerts = stock_summary(db, pid)
    checks = db.execute("SELECT c.*, st.status AS step_status, st.paid_at FROM step_checks c JOIN steps st ON "
                        "st.id = c.step_id WHERE c.project_id = ?", (pid,)).fetchall()
    paid_without = set()
    for c in checks:
        if c["required"] and c["step_status"] in ("paye", "versement") and (
                c["status"] != "conforme" or (c["paid_at"] and c["checked_at"] and c["checked_at"] > c["paid_at"])):
            paid_without.add(c["step_id"])
    insp = db.execute("SELECT verdict FROM inspections WHERE project_id = ? AND status = 'realisee'", (pid,)).fetchall()
    q_issues = q_open_issues(db, project_id=pid)
    return {
        "quality_reviews": db.execute("SELECT COUNT(*) FROM quality_reviews WHERE project_id = ? AND status IN ('pret', 'clos')",
                                      (pid,)).fetchone()[0],
        "quality_problems": len(q_issues), "quality_critical": len([x for x in q_issues if x["severity"] == "critique"]),
        "plan_gaps": db.execute("SELECT COUNT(*) FROM plan_items WHERE project_id = ? AND status IN ('ecart', 'a_verifier')",
                                (pid,)).fetchone()[0],
        "declared_pct": s["declared_pct"], "verified_pct": s["verified_pct"],
        "stale_pct": round(sum(st["amount"] for st in s["steps"] if st["status"] == "declare" and st["declared_at"]
                               and (datetime.now(timezone.utc) - datetime.fromisoformat(st["declared_at"])).days > 7)
                           * 100 / s["total"]) if s["total"] else 0,
        "ai_doubtful": db.execute("SELECT COUNT(*) FROM proofs WHERE project_id = ? AND ok = 1 AND "
                                  "(ai_same_site = 0 OR ai_construction = 0)", (pid,)).fetchone()[0],
        "delay": (pred["delay"] if pred and not pred.get("done") else 0 if pred else None),
        "has_material_data": bool(plans or lines),
        "material_alerts": len(mat_alerts), "stock_alerts": len(stock_alerts),
        "unpaid_orders": db.execute("SELECT COUNT(*) FROM orders WHERE project_id = ? AND status = 'a_payer'", (pid,)).fetchone()[0],
        "proofs_total": s["proofs_total"], "refused": s["refused"], "days_silent": s["days_silent"],
        "started": any(st["status"] != "attente" for st in s["steps"]),
        "checks_total": len(checks), "paid_without_checks": len(paid_without),
        "checks_made_optional": len([c for c in checks if c["made_optional"]]),
        "checks_overdue": len([c for c in checks if c["required"] and c["status"] != "conforme" and c["step_status"] == "declare"]),
        "checks_done": len([c for c in checks if c["status"] != "a_faire"]),
        "checks_nonconform": len([c for c in checks if c["status"] == "non_conforme"]),
        "inspections_done": len(insp), "inspections_nc": len([i for i in insp if i["verdict"] == "non_conforme"]),
        "inspections_reserves": len([i for i in insp if i["verdict"] == "reserves"]),
    }


def project_trust(p, s=None, pred=None, db=None):
    db = db or get_db()
    s = s or project_stats(p["id"], db)
    if pred is None:
        pred = project_prediction(p, s, db)
    return TRUST.compute(trust_inputs(db, p, s, pred))


@app.route("/chantiers/<int:project_id>/confiance")
@login_required
def trust_page(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "admin", "intervenant"))
    return render_template("trust.html", p=p, t=project_trust(p), role=g.project_role)


# --------------------------------------------------------------------------
# Achat direct des materiaux : catalogue des fournisseurs, commandes, livraison prouvee
# --------------------------------------------------------------------------
ORDER_STATUS = {
    "proposee": "Proposée par le chef de chantier", "envoyee": "Envoyée au fournisseur", "acceptee": "Acceptée, livraison prévue",
    "refusee": "Refusée par le fournisseur", "livree": "Livrée, réception à confirmer", "receptionnee": "Reçue et payée",
    "a_payer": "Reçue, à payer au fournisseur", "litige": "Problème signalé", "annulee": "Annulée",
}
ORDER_OPEN = ("proposee", "envoyee", "acceptee", "livree", "litige")


def commission_pct():
    try:
        return max(0.0, min(30.0, float(env("COMMISSION_MATERIAUX", "3"))))
    except ValueError:
        return 3.0


@app.template_filter("qte")
def qte_filter(x):
    """Quantite lisible : 120 au lieu de 120.0, 2,5 en francais."""
    if x is None:
        return "–"
    t = f"{float(x):g}"
    return t.replace(".", ",") if I18N.current_lang() == "fr" else t


def get_order(oid):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if o is None:
        abort(404)
    p = db.execute("SELECT * FROM projects WHERE id = ?", (o["project_id"],)).fetchone()
    me = current_user()
    role = project_role(p)
    if me and me["id"] == o["supplier_id"]:
        role = "fournisseur"
    if role not in ("owner", "chef", "fournisseur", "admin"):
        abort(403)
    g.order_role = role
    return o, p


def order_lines(oid, db=None):
    return (db or get_db()).execute("SELECT * FROM order_lines WHERE order_id = ? ORDER BY id", (oid,)).fetchall()


def set_order(db, oid, **fields):
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE orders SET {cols} WHERE id = ?", (*fields.values(), oid))


def supplier_of(db, o):
    return db.execute("SELECT * FROM users WHERE id = ?", (o["supplier_id"],)).fetchone()


def reserve_order_funds(db, p, o):
    """Reserve le montant de la commande sur le sequestre. Retourne un message d'erreur ou None."""
    if p["pay_mode"] != "sequestre":
        set_order(db, o["id"], pay_mode=p["pay_mode"] if p["pay_mode"] in ("manuel", "suivi") else "manuel")
        return None
    esc = escrow(p["id"], db)
    if esc["balance"] < o["total"]:
        return _("Solde du séquestre insuffisant : déposez au moins %(v)s FCFA.",
                 v=f"{o['total'] - esc['balance']:,}".replace(",", " "))
    prov = PAY.get_provider()
    db.execute("INSERT INTO transactions (project_id, user_id, kind, amount, provider, ref, status, created_at, updated_at, "
               "order_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (p["id"], current_user()["id"], "versement", o["total"], prov.name, tx_ref(p["id"]), "en_attente",
                now_iso(), now_iso(), o["id"]))
    set_order(db, o["id"], pay_mode="sequestre")
    return None


def release_order_funds(db, o):
    db.execute("UPDATE transactions SET status = 'annule', updated_at = ? WHERE order_id = ? AND status = 'en_attente'",
               (now_iso(), o["id"]))


def order_invoice(db, o, lines, supplier):
    """La livraison confirmee devient une facture verifiee : elle alimente le controle des materiaux."""
    total = sum(round((ln["qty_received"] or 0) * ln["unit_price"]) for ln in lines)
    cur = db.execute("INSERT INTO invoices (project_id, step_id, user_id, filename, media_type, sha256, supplier, number, "
                     "inv_date, total, status, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (o["project_id"], o["step_id"], o["created_by"], str(o["id"]), "commande", f"commande-{o['ref']}",
                      supplier["name"], o["ref"], now_iso()[:10], total, "validee", None, now_iso()))
    for ln in lines:
        if ln["qty_received"]:
            db.execute("INSERT INTO invoice_lines (invoice_id, step_id, material, raw_label, unit, qty, unit_price) "
                       "VALUES (?,?,?,?,?,?,?)", (cur.lastrowid, o["step_id"], ln["material"], ln["name"], ln["unit"],
                                                  ln["qty_received"], ln["unit_price"]))


def settle_order(db, p, o, received):
    """Paie le fournisseur pour ce qui a ete recu, moins la commission. Retourne le nouveau statut."""
    supplier = supplier_of(db, o)
    commission = round(received * commission_pct() / 100)
    if o["pay_mode"] != "sequestre":
        set_order(db, o["id"], status="a_payer", received_total=received, commission=commission, received_at=now_iso())
        if o["pay_mode"] == "suivi":
            pay_open_notify(db, p, payment_due(db, "commande", o["id"]), current_user()["id"] if current_user() else None)
        return "a_payer"
    tx = db.execute("SELECT * FROM transactions WHERE order_id = ? AND status = 'en_attente'", (o["id"],)).fetchone()
    prov = PAY.get_provider()
    try:
        r = prov.payout(tx["ref"] if tx else tx_ref(p["id"]), received - commission, supplier["phone"], supplier["name"],
                        public_url(url_for("cinetpay_notify", secret=notify_url_secret())) or "")
    except Exception as e:
        r = {"status": "echoue", "error": str(e)[:200]}
    if tx:
        db.execute("UPDATE transactions SET amount = ?, status = ?, provider_ref = ?, error = ?, updated_at = ? WHERE id = ?",
                   (received, "reussi" if r["status"] == "reussi" else r["status"], r.get("provider_ref"),
                    r.get("error"), now_iso(), tx["id"]))
    if r["status"] == "echoue":
        set_order(db, o["id"], status="a_payer", received_total=received, commission=commission, received_at=now_iso())
        log(p["id"], L("Paiement du fournisseur échoué pour la commande %(ref)s : %(v)s", ref=o["ref"], v=r.get("error") or ""),
            db)
        return "a_payer"
    set_order(db, o["id"], status="receptionnee", received_total=received, commission=commission, received_at=now_iso(),
              pay_ref=r.get("provider_ref") or (tx["ref"] if tx else None))
    return "receptionnee"


@app.route("/fournisseur/catalogue", methods=["GET", "POST"])
@role_required("fournisseur")
def supplier_catalog():
    me = current_user()
    db = get_db()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "add":
            name, price = f.get("name", "").strip()[:120], to_int(f.get("price"))
            if not name or price <= 0:
                flash(_("Indiquez le nom du produit et son prix."), "error")
            else:
                db.execute("INSERT INTO products (supplier_id, material, name, unit, price, created_at) VALUES (?,?,?,?,?,?)",
                           (me["id"], MAT.normalize(f.get("material") or name), name, f.get("unit", "").strip()[:20] or "u",
                            price, now_iso()))
        elif action in ("price", "toggle", "delete"):
            pid = to_int(f.get("product_id"))
            prod = db.execute("SELECT * FROM products WHERE id = ? AND supplier_id = ?", (pid, me["id"])).fetchone()
            if prod is None:
                abort(404)
            if action == "price" and to_int(f.get("price")) > 0:
                db.execute("UPDATE products SET price = ? WHERE id = ?", (to_int(f.get("price")), pid))
            elif action == "toggle":
                db.execute("UPDATE products SET available = ? WHERE id = ?", (0 if prod["available"] else 1, pid))
            elif action == "delete":
                if db.execute("SELECT 1 FROM order_lines WHERE product_id = ?", (pid,)).fetchone():
                    db.execute("UPDATE products SET available = 0 WHERE id = ?", (pid,))   # garde l'historique
                else:
                    db.execute("DELETE FROM products WHERE id = ?", (pid,))
        db.commit()
        return redirect(url_for("supplier_catalog"))
    products = db.execute("SELECT * FROM products WHERE supplier_id = ? ORDER BY material, name", (me["id"],)).fetchall()
    return render_template("supplier_catalog.html", products=products, commission=commission_pct())


def verified_suppliers(db):
    return db.execute("SELECT u.*, (SELECT COUNT(*) FROM products pr WHERE pr.supplier_id = u.id AND pr.available = 1) AS n "
                      "FROM users u WHERE u.role = 'fournisseur' AND u.verified = 1 AND u.blocked = 0 AND u.deleted = 0 "
                      "AND u.supplier_terms_at IS NOT NULL "
                      "ORDER BY u.zone, u.name").fetchall()


@app.route("/chantiers/<int:project_id>/commandes/nouvelle", methods=["GET", "POST"])
@login_required
def new_order(project_id):
    p = load_project(project_id, roles=("owner", "chef"))
    role = g.project_role
    db = get_db()
    steps = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    sid = to_int(request.values.get("fournisseur"), None)
    supplier = db.execute("SELECT * FROM users WHERE id = ? AND role = 'fournisseur' AND verified = 1 AND blocked = 0 "
                          "AND supplier_terms_at IS NOT NULL",
                          (sid,)).fetchone() if sid else None
    if request.method == "POST":
        if not supplier:
            abort(400)
        step = get_step(project_id, to_int(request.form.get("step_id")))
        lines = []
        for prod in db.execute("SELECT * FROM products WHERE supplier_id = ? AND available = 1", (supplier["id"],)):
            q = to_float(request.form.get(f"qty_{prod['id']}"))
            if q and q > 0:
                lines.append((prod, q))
        if not lines:
            flash(_("Indiquez au moins une quantité."), "error")
            return redirect(url_for("new_order", project_id=project_id, fournisseur=supplier["id"]))
        total = sum(round(q * prod["price"]) for prod, q in lines)
        ref = f"CMD-{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(3).upper()}"
        cur = db.execute("INSERT INTO orders (ref, project_id, step_id, supplier_id, created_by, status, pay_mode, total, note, "
                         "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (ref, project_id, step["id"], supplier["id"], current_user()["id"],
                          "proposee" if role == "chef" else "envoyee", p["pay_mode"], total,
                          request.form.get("note", "").strip()[:500] or None, now_iso(), now_iso()))
        oid = cur.lastrowid
        for prod, q in lines:
            db.execute("INSERT INTO order_lines (order_id, product_id, material, name, unit, qty, unit_price) VALUES (?,?,?,?,?,?,?)",
                       (oid, prod["id"], prod["material"], prod["name"], prod["unit"], q, prod["price"]))
        o = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if role == "chef":
            log(project_id, L("Commande de matériaux proposée : %(ref)s, %(total)s FCFA", ref=ref,
                              total=f"{total:,}".replace(",", " ")))
            notify(project_id, owners_of(p), L("Commande de matériaux à approuver"),
                   L("Le chef de chantier propose d'acheter %(total)s FCFA de matériaux chez %(name)s.",
                     total=f"{total:,}".replace(",", " "), name=supplier["name"]), url_for("order", oid=oid), important=True)
            db.commit()
            flash(_("Commande proposée au propriétaire."), "ok")
            return redirect(url_for("order", oid=oid))
        err = reserve_order_funds(db, p, o)
        if err:
            set_order(db, oid, status="proposee")
            db.commit()
            flash(err, "error")
            return redirect(url_for("order", oid=oid))
        send_order(db, p, o, supplier)
        db.commit()
        flash(_("Commande envoyée au fournisseur."), "ok")
        return redirect(url_for("order", oid=oid))
    products, warnings = [], {}
    if supplier:
        products = db.execute("SELECT * FROM products WHERE supplier_id = ? AND available = 1 ORDER BY material, name",
                              (supplier["id"],)).fetchall()
        refs = {(pl["step_id"], pl["material"]): pl["unit_price_ref"] for pl in
                db.execute("SELECT * FROM materials_plan WHERE project_id = ? AND unit_price_ref > 0", (project_id,))}
        for prod in products:
            for st in steps:
                ref_price = refs.get((st["id"], prod["material"]))
                if ref_price and prod["price"] > ref_price * MAT.OVER_PRICE:
                    warnings[prod["id"]] = _("Plus cher que votre prix de référence (%(v)s FCFA)", v=f"{int(ref_price):,}"
                                             .replace(",", " "))
    current = project_stats(project_id)["current"]
    return render_template("order_new.html", p=p, role=role, steps=steps, suppliers=verified_suppliers(db),
                           supplier=supplier, products=products, warnings=warnings, current=current,
                           commission=commission_pct())


def send_order(db, p, o, supplier):
    set_order(db, o["id"], status="envoyee")
    log(p["id"], L("Commande %(ref)s envoyée à %(name)s (%(total)s FCFA)", ref=o["ref"], name=supplier["name"],
                   total=f"{o['total']:,}".replace(",", " ")), db)
    notify(p["id"], [supplier["id"]], L("Nouvelle commande"),
           L("%(total)s FCFA de matériaux à livrer à %(address)s.", total=f"{o['total']:,}".replace(",", " "),
             address=p["address"] or p["name"]), url_for("order", oid=o["id"]), important=True, db=db)


@app.route("/commandes/<int:oid>", methods=["GET", "POST"])
@login_required
def order(oid):
    o, p = get_order(oid)
    role = g.order_role
    db = get_db()
    me = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        supplier = supplier_of(db, o)
        back = redirect(url_for("order", oid=oid))
        if action == "approve" and role == "owner" and o["status"] == "proposee":
            err = reserve_order_funds(db, p, o)
            if err:
                flash(err, "error")
                return back
            send_order(db, p, o, supplier)
            notify(p["id"], [p["chef_id"]], L("Commande approuvée"), L("La commande %(ref)s est envoyée au fournisseur.",
                                                                       ref=o["ref"]), url_for("order", oid=oid), db=db)
            flash(_("Commande envoyée au fournisseur."), "ok")
        elif action == "cancel" and role in ("owner", "admin") and o["status"] in ("proposee", "envoyee", "acceptee", "litige"):
            release_order_funds(db, o)
            set_order(db, oid, status="annulee")
            log(p["id"], L("Commande %(ref)s annulée", ref=o["ref"]), db)
            notify(p["id"], [supplier["id"], p["chef_id"]], L("Commande annulée"),
                   L("La commande %(ref)s est annulée.", ref=o["ref"]), url_for("order", oid=oid), db=db)
            flash(_("Commande annulée. L'argent réservé est libéré."), "ok")
        elif action == "accept" and role == "fournisseur" and o["status"] == "envoyee":
            d_ = request.form.get("delivery_date") or None
            set_order(db, oid, status="acceptee", delivery_date=d_)
            log(p["id"], L("Commande %(ref)s acceptée par %(name)s", ref=o["ref"], name=me["name"]), db, me["id"])
            notify(p["id"], owners_of(p, db) + [p["chef_id"]], L("Livraison prévue"),
                   L("%(name)s livrera la commande %(ref)s le %(d)s.", name=me["name"], ref=o["ref"],
                     d=format_d(d_) or "?"), url_for("order", oid=oid), important=True, db=db)
            flash(_("Commande acceptée."), "ok")
        elif action == "refuse" and role == "fournisseur" and o["status"] == "envoyee":
            release_order_funds(db, o)
            set_order(db, oid, status="refusee", problem=request.form.get("motif", "").strip()[:300] or None)
            log(p["id"], L("Commande %(ref)s refusée par %(name)s", ref=o["ref"], name=me["name"]), db, me["id"])
            notify(p["id"], owners_of(p, db) + [p["chef_id"]], L("Commande refusée"),
                   L("%(name)s ne peut pas livrer la commande %(ref)s. L'argent réservé est libéré.", name=me["name"],
                     ref=o["ref"]), url_for("order", oid=oid), important=True, db=db)
            flash(_("Commande refusée."), "ok")
        elif action == "receive" and role in ("chef", "owner") and o["status"] in ("livree", "litige"):
            lines = order_lines(oid)
            declared = {}
            for ln in lines:
                q = to_float(request.form.get(f"qty_{ln['id']}"))
                declared[ln["id"]] = ln["qty"] if q is None else max(0.0, min(q, ln["qty"]))
            gaps = count_gaps(db, oid, declared)
            if gaps and not (role == "owner" and request.form.get("confirm_gap") == "1"):
                detail = "; ".join(f"{ln['name']} : {fmt_qty(q)} déclarés, {fmt_qty(n)} comptés sur la photo" for ln, q, n in gaps)
                set_order(db, oid, status="litige", problem=f"Écart de comptage : {detail}")
                log(p["id"], L("Commande %(ref)s : écart entre la réception déclarée et le comptage de la photo (%(v)s)", ref=o["ref"], v=detail), db)
                notify(p["id"], owners_of(p, db), L("Écart de comptage sur une livraison"),
                       L("Commande %(ref)s : %(v)s. Le paiement du fournisseur attend votre confirmation.", ref=o["ref"], v=detail),
                       url_for("order", oid=oid, _anchor="comptage"), important=True, db=db)
                db.commit()
                flash(_("Les quantités déclarées ne correspondent pas au comptage de la photo. Le propriétaire doit confirmer avant le paiement du fournisseur."), "error")
                return back
            received = 0
            short = []
            for ln in lines:
                q = to_float(request.form.get(f"qty_{ln['id']}"))
                q = ln["qty"] if q is None else max(0.0, min(q, ln["qty"]))
                db.execute("UPDATE order_lines SET qty_received = ? WHERE id = ?", (q, ln["id"]))
                received += round(q * ln["unit_price"])
                if q < ln["qty"]:
                    short.append(f"{ln['name']} : {q:g}/{ln['qty']:g} {ln['unit']}")
            for ln in order_lines(oid):
                if ln["qty_received"]:
                    add_stock_move(db, p, ln["material"], ln["unit"], ln["qty_received"], "entree", me["id"], o["step_id"],
                                   "commande", oid, o["ref"])
            status = settle_order(db, p, o, received)
            emit_event(db, p["id"], "commande.receptionnee", {"commande": o["ref"], "recu_fcfa": received, "commande_fcfa": o["total"],
                                                              "manquant": short})
            lines = order_lines(oid)
            order_invoice(db, db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone(), lines, supplier)
            log(p["id"], L("Commande %(ref)s reçue : %(v)s FCFA de matériaux", ref=o["ref"],
                           v=f"{received:,}".replace(",", " ")) + (L(" (manquant : %(v)s)", v="; ".join(short)) if short else ""),
                db)
            notify(p["id"], owners_of(p, db), L("Matériaux reçus") if not short else L("Livraison incomplète"),
                   L("Commande %(ref)s : %(v)s FCFA reçus sur %(t)s.", ref=o["ref"], v=f"{received:,}".replace(",", " "),
                     t=f"{o['total']:,}".replace(",", " ")), url_for("order", oid=oid), important=bool(short), db=db)
            notify(p["id"], [supplier["id"]], L("Paiement envoyé") if status == "receptionnee" else L("Livraison confirmée"),
                   L("Commande %(ref)s : %(v)s FCFA, commission déduite.", ref=o["ref"],
                     v=f"{received - round(received * commission_pct() / 100):,}".replace(",", " ")),
                   url_for("order", oid=oid), important=True, db=db)
            flash(_("Réception enregistrée.") + (" " + _("Le fournisseur est payé pour ce qui a été livré.")
                                                  if status == "receptionnee" else ""), "ok")
        elif action == "problem" and role in ("chef", "owner") and o["status"] in ("acceptee", "livree"):
            text = request.form.get("text", "").strip()[:500]
            if len(text) < 10:
                flash(_("Décrivez le problème (10 caractères minimum)."), "error")
                return back
            set_order(db, oid, status="litige", problem=text)
            log(p["id"], L("Problème signalé sur la commande %(ref)s : %(v)s", ref=o["ref"], v=text), db)
            notify(p["id"], owners_of(p, db) + [supplier["id"]] + admins(db, "disputes"), L("Problème sur une livraison"),
                   L("Commande %(ref)s : %(v)s", ref=o["ref"], v=text), url_for("order", oid=oid), important=True, db=db)
            flash(_("Problème signalé. Le paiement du fournisseur est suspendu."), "ok")
        elif action == "paid" and role == "owner" and o["status"] == "a_payer" and o["pay_mode"] != "suivi":
            set_order(db, oid, status="receptionnee", pay_ref=request.form.get("pay_ref", "").strip()[:80] or None)
            log(p["id"], L("Fournisseur payé pour la commande %(ref)s", ref=o["ref"]), db)
            flash(_("Paiement enregistré."), "ok")
        else:
            flash(_("Action impossible à cette étape de la commande."), "error")
            return back
        db.commit()
        return back
    supplier = supplier_of(db, o)
    step = db.execute("SELECT * FROM steps WHERE id = ?", (o["step_id"],)).fetchone()
    photos = db.execute("SELECT proofs.*, steps.name AS step_name, users.name AS author FROM proofs JOIN steps ON "
                        "steps.id = proofs.step_id JOIN users ON users.id = proofs.user_id WHERE order_id = ? ORDER BY proofs.id DESC",
                        (oid,)).fetchall()
    ctx = dict(o=o, p=p, role=role, lines=order_lines(oid), supplier=supplier, step=step, photos=photos,
               ORDER_STATUS={k: _(v) for k, v in ORDER_STATUS.items()}, commission=commission_pct())
    if (role == "fournisseur" and o["status"] in ("acceptee", "livree")) or (role in ("chef", "owner") and o["status"] in ("livree", "litige")):
        ctx["capture_token"] = new_capture_token(db, p["id"])
    ctx["counts"] = order_counts(db, oid)
    ctx["count_on"] = COUNT.ai_enabled()
    ctx["count_guides"] = [(ln["name"], COUNT.guide(ln["material"], g.lang)) for ln in ctx["lines"]]
    ctx["count_status"] = {ln["id"]: COUNT.compare(ln["qty"], ln["qty_received"], (ctx["counts"].get(ln["id"]) or {"ai_count": None})["ai_count"],
                                                   (ctx["counts"].get(ln["id"]) or {"ai_conf": None})["ai_conf"]) for ln in ctx["lines"]}
    return render_template("order.html", **ctx)


@app.route("/commandes/<int:oid>/livraison", methods=["POST"])
@role_required("fournisseur")
def order_delivery(oid):
    o, p = get_order(oid)
    if g.order_role != "fournisseur" or o["status"] not in ("acceptee", "livree"):
        abort(403)
    db = get_db()
    step = db.execute("SELECT * FROM steps WHERE id = ?", (o["step_id"],)).fetchone()
    ok, reasons = process_proof(p, step, current_user(), source="fournisseur", order_id=oid)
    if ok is None:
        flash(reasons, "error")
    elif ok:
        if o["status"] != "livree":
            set_order(db, oid, status="livree", delivered_at=now_iso())
            log(p["id"], L("Commande %(ref)s livrée sur le terrain (photo vérifiée)", ref=o["ref"]))
            notify(p["id"], [p["chef_id"]] + owners_of(p), L("Livraison à confirmer"),
                   L("La commande %(ref)s est livrée. Comptez les matériaux et confirmez les quantités reçues.", ref=o["ref"]),
                   url_for("order", oid=oid), important=True)
            db.commit()
        if COUNT.ai_enabled():
            run_async(count_order, oid)
        flash(_("Photo de livraison vérifiée. Le chef de chantier va confirmer les quantités."), "ok")
    else:
        flash(_("Photo refusée : ") + "; ".join(map(I18N.render, reasons)), "error")
    return redirect(url_for("order", oid=oid))


# --------------------------------------------------------------------------
# Marche public (SIGOMAP)
# --------------------------------------------------------------------------
@app.route("/chantiers/<int:project_id>/marche", methods=["POST"])
@login_required
def update_market(project_id):
    p = load_project(project_id, roles=("owner",))
    f = request.form
    url = f.get("sigomap_url", "").strip()
    if url and not url.startswith(("https://", "http://")):
        url = ""
    kind = "public" if f.get("kind") == "public" else "prive"
    db = get_db()
    db.execute("UPDATE projects SET kind = ?, is_public = ?, marche_ref = ?, ao_ref = ?, autorite = ?, attributaire = ?, "
               "montant_marche = ?, sigomap_url = ?, description = ? WHERE id = ?",
               (kind, 1 if kind == "public" and f.get("is_public") else 0, f.get("marche_ref", "").strip()[:60] or None,
                f.get("ao_ref", "").strip()[:60] or None, f.get("autorite", "").strip()[:150] or None,
                f.get("attributaire", "").strip()[:150] or None, to_int(f.get("montant_marche"), None), url or None,
                f.get("description", "").strip()[:2000] or None, project_id))
    db.execute("UPDATE documents SET is_public = ? WHERE project_id = ? AND category = 'PV'",
               (1 if kind == "public" and f.get("is_public") else 0, project_id))
    log(project_id, L('Informations du marché mises à jour'))
    db.commit()
    flash(_('Informations du marché enregistrées.') + (_(' Le chantier est visible sur le portail citoyen.')
                                                     if kind == "public" and f.get("is_public") else ""), "ok")
    return redirect(url_for("project", project_id=p["id"], onglet="dossier"))


IMPORT_COLUMNS = {
    "marche_ref": ["reference", "ref", "n marche", "numero marche", "num marche", "marche"],
    "name": ["objet", "intitule", "libelle", "nom", "projet"],
    "autorite": ["autorite contractante", "autorite", "ac", "maitre d'ouvrage", "maitre douvrage"],
    "attributaire": ["attributaire", "titulaire", "entreprise", "prestataire"],
    "montant_marche": ["montant", "montant ttc", "montant ht", "montant du marche"],
    "ao_ref": ["appel d'offres", "appel doffres", "ao", "dao", "n ao", "avis"],
    "address": ["localite", "lieu", "adresse", "localisation", "commune", "region"],
    "lat": ["latitude", "lat"],
    "lng": ["longitude", "lng", "lon", "long"],
    "start_date": ["date de demarrage", "demarrage", "date debut", "debut", "ordre de service", "date os"],
    "sigomap_url": ["lien", "url", "lien sigomap"],
}


def _map_header(header):
    clean = [plain(h).strip().replace("°", "").replace(".", "") for h in header]
    mapping = {}
    for key, names in IMPORT_COLUMNS.items():
        for i, h in enumerate(clean):
            if h in names and i not in mapping.values():
                mapping[key] = i
                break
        if key not in mapping:
            for i, h in enumerate(clean):
                if any(h.startswith(n) for n in names) and i not in mapping.values():
                    mapping[key] = i
                    break
    return mapping


@app.route("/marches/import", methods=["GET", "POST"])
@role_required("proprio")
def import_markets():
    result = None
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash(_('Choisissez le fichier CSV exporté.'), "error")
            return redirect(url_for("import_markets"))
        raw = file.read().decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(raw[:4000], delimiters=";,\t") if raw.strip() else csv.excel
        rows = list(csv.reader(io.StringIO(raw), dialect))
        if len(rows) < 2:
            flash(_('Le fichier est vide.'), "error")
            return redirect(url_for("import_markets"))
        m = _map_header(rows[0])
        if "marche_ref" not in m and "name" not in m:
            flash(_('Colonnes « Référence » ou « Objet » introuvables.'), "error")
            return redirect(url_for("import_markets"))
        db = get_db()
        me = current_user()
        result = {"created": 0, "updated": 0, "skipped": []}
        for n, row in enumerate(rows[1:], start=2):
            get = lambda k: row[m[k]].strip() if k in m and m[k] < len(row) else ""
            ref, name = get("marche_ref"), get("name") or get("marche_ref")
            if not name:
                continue
            market = {"marche_ref": ref or None, "autorite": get("autorite") or None,
                      "attributaire": get("attributaire") or None,
                      "montant_marche": to_int(get("montant_marche"), None), "ao_ref": get("ao_ref") or None,
                      "sigomap_url": get("sigomap_url") if get("sigomap_url").startswith("http") else None,
                      "is_public": True}
            existing = db.execute("SELECT * FROM projects WHERE owner_id = ? AND marche_ref = ?",
                                  (me["id"], ref)).fetchone() if ref else None
            if existing:
                db.execute("UPDATE projects SET autorite = COALESCE(?, autorite), attributaire = COALESCE(?, attributaire), "
                           "montant_marche = COALESCE(?, montant_marche), ao_ref = COALESCE(?, ao_ref), "
                           "sigomap_url = COALESCE(?, sigomap_url) WHERE id = ?",
                           (market["autorite"], market["attributaire"], market["montant_marche"], market["ao_ref"],
                            market["sigomap_url"], existing["id"]))
                result["updated"] += 1
                continue
            lat, lng = to_float(get("lat")), to_float(get("lng"))
            if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
                result["skipped"].append(f"Ligne {n} ({name[:40]}) : coordonnées GPS manquantes")
                continue
            total = market["montant_marche"] or 0
            steps = [(sn, round(total * share), days) for sn, share, days in PUBLIC_STEPS]
            start = get("start_date")
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    start = datetime.strptime(start, fmt).date().isoformat()
                    break
                except ValueError:
                    continue
            else:
                start = date.today().isoformat()
            create_project(db, me["id"], name[:150], get("address"), lat, lng, 300, steps, start, kind="public",
                           market=market)
            result["created"] += 1
        db.commit()
    return render_template("import_markets.html", result=result, columns=IMPORT_COLUMNS)


# --------------------------------------------------------------------------
# Comptes rendus hebdomadaires
# --------------------------------------------------------------------------
def build_report(db, p, end=None):
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    s_iso, e_iso = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
    s = project_stats(p["id"], db)
    pred = project_prediction(p, s, db)
    prf = db.execute("SELECT * FROM proofs WHERE project_id = ? AND created_at >= ? AND created_at <= ? ORDER BY id",
                     (p["id"], s_iso, e_iso)).fetchall()
    ok = [x for x in prf if x["ok"]]
    declared = [st["name"] for st in s["steps"] if st["declared_at"] and s_iso <= st["declared_at"] <= e_iso]
    validated = [st for st in s["steps"] if st["paid_at"] and s_iso <= st["paid_at"] <= e_iso]
    released = sum(st["amount"] for st in validated)
    insp = db.execute("SELECT verdict FROM inspections WHERE project_id = ? AND done_at >= ? AND done_at <= ?",
                      (p["id"], s_iso, e_iso)).fetchall()
    alerts = [a[0] + " – " + a[2] for a in project_alerts(p, s, pred, db)]
    summary = []
    if ok:
        summary.append(_('%(len)s preuve(s) vérifiée(s) cette semaine', len=len(ok))
                       + (_(' pour « %(name)s »', name=s['current']['name']) if s["current"] else "") + ".")
    else:
        summary.append(_('Aucune preuve vérifiée cette semaine.'))
    if declared:
        summary.append(I18N.pl(len(declared), 'Étape(s) déclarée(s) terminée(s) : ') + ", ".join(declared) + ".")
    if validated:
        summary.append(_('%(len)s étape(s) validée(s), %(released)s FCFA versés.', len=len(validated), released=format(released, ',')).replace(",", " "))
    if pred and not pred["done"]:
        summary.append(_('Fin estimée le %(format_d)s', format_d=format_d(pred['predicted_end']))
                       + (_(', soit %(delay)s jours de retard.', delay=pred['delay']) if pred["delay"] > 0 else _(', dans les temps.')))
    return {
        "period_start": s_iso, "period_end": e_iso, "summary": summary,
        "proofs_ok": len(ok), "proofs_bad": len(prf) - len(ok), "proof_ids": [x["id"] for x in ok][-6:],
        "declared": declared, "validated": [st["name"] for st in validated], "released": released,
        "current": s["current"]["name"] if s["current"] else None,
        "verified_pct": s["verified_pct"], "declared_pct": s["declared_pct"],
        "locked": s["locked"], "paid": s["paid"], "total": s["total"], "sequestre": s["sequestre"],
        "prediction": {k: (format_d(v) if isinstance(v, date) else v) for k, v in pred.items()} if pred else None,
        "inspections": [VERDICTS.get(i["verdict"], "") for i in insp], "alerts": alerts,
    }


def save_report(db, p):
    owner = db.execute("SELECT lang FROM users WHERE id = ?", (p["owner_id"],)).fetchone()
    previous = getattr(g, "lang", None)
    g.lang = (owner["lang"] if owner and owner["lang"] else None) or I18N.DEFAULT
    try:
        content = build_report(db, p)
    finally:
        g.lang = previous or I18N.DEFAULT
    cur = db.execute("INSERT INTO reports (project_id, period_start, period_end, content, created_at) VALUES (?,?,?,?,?)",
                     (p["id"], content["period_start"], content["period_end"], json.dumps(content, ensure_ascii=False),
                      now_iso()))
    rid = cur.lastrowid
    with app.test_request_context():
        notify(p["id"], owners_of(p, db), L('Compte rendu de la semaine – %(name)s', name=p['name']),
               " ".join(content["summary"]), f"/chantiers/{p['id']}/rapports/{rid}", important=True, db=db)
    db.commit()
    return rid


def report_due(db, p):
    last = db.execute("SELECT created_at FROM reports WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                      (p["id"],)).fetchone()
    ref = last["created_at"] if last else p["created_at"]
    return datetime.now(timezone.utc) - datetime.fromisoformat(ref) >= timedelta(days=7)


def maybe_weekly_report(p):
    db = get_db()
    if report_due(db, p):
        save_report(db, p)


@app.cli.command("rapports-hebdo")
def weekly_reports_cli():
    """Genere les comptes rendus dus et les images satellite du mois (a lancer chaque jour)."""
    db = connect()
    n = 0
    for p in db.execute("SELECT * FROM projects").fetchall():
        if report_due(db, p):
            save_report(db, p)
            n += 1
    sat = monthly_satellite(db)
    db.close()
    print(f"{n} compte(s) rendu(s) généré(s), {sat} image(s) satellite téléchargée(s).")


def retry_pending(db):
    """Relance ce qu'un redemarrage du serveur a pu interrompre. Retourne un resume."""
    try:
        deliver_webhooks()
    except Exception as e:
        app.logger.warning("webhooks : %s", e)
    ago = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat()
    ids = [r[0] for r in db.execute("SELECT id FROM notifications WHERE status = 'en_attente' AND created_at < ?",
                                    (ago(2),))]
    if ids:
        _send_pending(ids)
    proofs = [r[0] for r in db.execute("SELECT id FROM proofs WHERE ai_status = 'en_cours' AND created_at < ?", (ago(5),))]
    for pid in proofs:
        if VISION.ai_enabled():
            analyse_proof(pid)
        else:
            db.execute("UPDATE proofs SET ai_status = 'off' WHERE id = ?", (pid,))
    invs = [r[0] for r in db.execute("SELECT id FROM invoices WHERE status = 'lecture_ia' AND created_at < ?", (ago(5),))]
    for iid in invs:
        if VISION.ai_enabled():
            read_invoice_job(iid)
        else:
            db.execute("UPDATE invoices SET status = 'a_saisir' WHERE id = ?", (iid,))
    txs = [r[0] for r in db.execute("SELECT ref FROM transactions WHERE status = 'en_attente' AND kind = 'depot' "
                                    "AND created_at < ?", (ago(5),))]
    for ref in txs:
        try:
            sync_transaction(db, ref)
        except Exception as e:  # operateur injoignable : on reessaiera
            app.logger.warning("transaction %s : %s", ref, e)
    db.commit()
    return f"{len(ids)} message(s), {len(proofs)} analyse(s) IA, {len(invs)} facture(s), {len(txs)} paiement(s) relancé(s)"


def backup(keep=14, with_files=True):
    """Copie coherente de la base (et des fichiers) dans BACKUP_DIR. Garde les `keep` dernieres."""
    import glob
    import tarfile
    folder = env("BACKUP_DIR") or os.path.join(INSTANCE_DIR, "sauvegardes")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if DB.is_pg():
        import subprocess
        db_copy = os.path.join(folder, f"chantiervrai-{stamp}.sql.gz")
        with open(db_copy, "wb") as fh:
            dump = subprocess.run(["pg_dump", "--no-owner", "--dbname", DB.database_url()], capture_output=True, check=True)
            import gzip
            fh.write(gzip.compress(dump.stdout))
    else:
        db_copy = os.path.join(folder, f"chantiervrai-{stamp}.db")
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(db_copy)
        src.backup(dst)
        dst.close()
        src.close()
    out = [db_copy]
    if with_files:
        arch = os.path.join(folder, f"fichiers-{stamp}.tar.gz")
        with tarfile.open(arch, "w:gz") as t:
            t.add(UPLOAD_DIR, arcname="uploads")
        out.append(arch)
    for pattern in ("chantiervrai-*.db", "chantiervrai-*.sql.gz", "fichiers-*.tar.gz"):
        old = sorted(glob.glob(os.path.join(folder, pattern)))[:-keep]
        for f in old:
            os.remove(f)
    return out


def backup_and_copy(keep=14, with_files=None):
    """Sauvegarde vérifiée, puis copie hors du serveur si un stockage distant est configuré.
    Avec la copie distante, les fichiers partent un à un (incrémental) : l'archive locale des fichiers est alors inutile.
    Renvoie un compte rendu (lignes de texte) ; l'état est gardé dans les réglages et les échecs alertent l'équipe."""
    remote = OFFSITE.configured()
    if with_files is None:
        with_files = not remote
    db = connect()
    lines, status = [], {"backup_ok": "0", "backup_error": ""}
    try:
        files = backup(keep, with_files)
        ok, detail = OPS.verify_dump(files[0])
        if not ok:
            raise IOError(f"sauvegarde illisible : {detail}")
        status.update(backup_ok="1", backup_last=now_iso(), backup_detail=detail, backup_file=os.path.basename(files[0]))
        lines += [f"Sauvegardé et vérifié ({detail}) : {f}" for f in files[:1]] + [f"Sauvegardé : {f}" for f in files[1:]]
        if remote:
            store = OFFSITE.Store()
            try:
                key = OPS.push_dump(store, files[0], keep=max(keep, 30))
                sent, same, errs = OPS.sync_files(store, db, UPLOAD_DIR, now=now_iso())
                if errs:
                    raise IOError("; ".join(errs[:3]))
                status.update(offsite_ok="1", offsite_last=now_iso(), offsite_error="",
                              offsite_detail=f"{sent} nouveau(x) fichier(s), {same} déjà copié(s)")
                lines.append(f"Copie distante : {key} ; fichiers : {sent} envoyé(s), {same} déjà à jour.")
            except Exception as e:  # reseau, cle
                status.update(offsite_ok="0", offsite_error=str(e)[:300])
                lines.append(f"ÉCHEC de la copie distante : {e}")
                alert_team("Copie distante des sauvegardes en échec", str(e)[:500], "offsite", every_minutes=12 * 60, db=db)
    except Exception as e:  # disque plein, pg_dump absent…
        status["backup_error"] = str(e)[:300]
        lines.append(f"ÉCHEC de la sauvegarde : {e}")
        alert_team("Sauvegarde en échec", str(e)[:500], "backup", every_minutes=12 * 60, db=db)
    for k, v in status.items():
        set_setting(db, "ops_" + k, v)
    db.commit()
    db.close()
    return lines


def alert_team(subject, body, key, every_minutes=60, db=None):
    """Alerte l'équipe technique par e-mail (ALERT_EMAILS, sinon les super-admins), au plus une fois par période."""
    own = db is None
    db = db or connect()
    try:
        last = get_setting("alert_" + key, None, db)
        now = datetime.now(timezone.utc)
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(minutes=every_minutes):
                    return "deja"
            except ValueError:
                pass
        set_setting(db, "alert_" + key, now.isoformat())
        db.commit()
        to = [e.strip() for e in (env("ALERT_EMAILS") or "").split(",") if e.strip()]
        if not to:
            to = [r["email"] for r in db.execute("SELECT email FROM users WHERE is_admin = 1 AND staff_role = 'super'")]
        app.logger.error("ALERTE %s : %s", subject, body)
        out = []
        for email in to:
            st, _d = NOTIFY.send("email", {"email": email, "phone": None}, "Alerte : " + subject,
                                 body + "\n\n" + (env("PUBLIC_URL") or "") + "/sante")
            out.append(st)
        return ",".join(out) or "personne"
    finally:
        if own:
            db.close()


@app.cli.command("relancer")
def retry_cli():
    """Relance les messages, analyses IA, lectures de factures et paiements interrompus (toutes les 5 min)."""
    with app.test_request_context():
        for line in retry_tasks():
            print(line)


@app.cli.command("sauvegarde")
@click.option("--sans-fichiers", is_flag=True, help="Sauvegarder seulement la base de donnees.")
@click.option("--garder", default=14, help="Nombre de sauvegardes conservees.")
def backup_cli(sans_fichiers, garder):
    """Sauvegarde la base et les fichiers, vérifie, et copie hors du serveur si OFFSITE_* est configuré."""
    with app.test_request_context():
        for line in backup_and_copy(garder, False if sans_fichiers else None):
            print(line)


@app.cli.command("restaurer")
@click.option("--fichier", default="", help="Sauvegarde locale à reprendre (.db ou .sql.gz).")
@click.option("--distant", is_flag=True, help="Reprendre la dernière sauvegarde du stockage distant.")
@click.option("--avec-fichiers", is_flag=True, help="Redescendre aussi les photos et documents du stockage distant.")
@click.option("--oui", is_flag=True, help="Confirmer : la base actuelle est remplacée.")
def restore_cli(fichier, distant, avec_fichiers, oui):
    """Restaure la base (et les fichiers) depuis une sauvegarde. L'ancienne base SQLite est gardée à côté."""
    if not oui:
        raise click.ClickException("La base actuelle sera remplacée : relancez avec --oui pour confirmer.")
    store = OFFSITE.Store() if (distant or avec_fichiers) else None
    if (distant or avec_fichiers) and not OFFSITE.configured():
        raise click.ClickException("Stockage distant non configuré (OFFSITE_ENDPOINT, OFFSITE_BUCKET, OFFSITE_KEY_ID, OFFSITE_SECRET).")
    dump = fichier
    if distant:
        dump = OPS.fetch_remote_dump(store, os.path.join(INSTANCE_DIR, "restauration"))
        print("Sauvegarde distante récupérée :", dump)
    if dump:
        if DB.is_pg():
            print("Base PostgreSQL restaurée :", OPS.restore_pg(dump, DB.database_url()))
        else:
            print("Base SQLite restaurée :", OPS.restore_sqlite(dump, DB_PATH), "(ancienne base : .avant-restauration)")
    if avec_fichiers:
        print(f"{OPS.restore_files(store, UPLOAD_DIR)} fichier(s) redescendu(s) dans {UPLOAD_DIR}")
    if not dump and not avec_fichiers:
        raise click.ClickException("Indiquez --fichier, --distant ou --avec-fichiers.")


MIGRATION_ORDER = ["users", "projects", "steps", "proofs", "activity", "transactions", "notifications", "reports",
                   "sat_images", "media3d", "documents", "materials_plan", "invoices", "invoice_lines", "inspections",
                   "signalements", "login_attempts", "reset_tokens", "project_members", "disputes", "dispute_messages",
                   "admin_log", "capture_tokens", "api_tokens", "devices", "attestation_nonces", "products", "orders",
                   "order_lines", "stock_moves", "stock_thresholds", "step_checks", "payment_approvals", "bim_models", "bim_storeys", "sensors",
                   "sensor_readings", "imagery_orders", "academy_progress",
                   "contractor_reviews", "plan_readings", "assistant_messages", "zones", "pano_visits", "work_items",
                   "work_progress", "api_keys", "webhooks", "webhook_deliveries", "settings", "subscriptions",
                   "billing_invoices", "inspection_requests", "payment_records", "quality_reviews", "quality_photos",
                   "quality_points", "quality_messages", "wa_sessions", "wa_messages", "site_notes",
                   "fin_profiles", "fin_sources", "fin_receipts", "fin_costs", "fin_documents", "land_files",
                   "land_requests", "delivery_counts", "plan_items", "plan_item_photos", "offsite_files"]


@app.cli.command("migrer-vers-postgres")
@click.argument("sqlite_file", default="")
def migrate_to_pg(sqlite_file):
    """Copie une base SQLite existante dans PostgreSQL (DATABASE_URL). A faire une seule fois, base PostgreSQL vide."""
    if not DB.is_pg():
        print("Définissez d'abord DATABASE_URL=postgresql://… vers la base PostgreSQL cible.")
        return
    src = sqlite3.connect(sqlite_file or DB_PATH)
    src.row_factory = sqlite3.Row
    dst = connect()
    if dst.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        print("La base PostgreSQL contient déjà des comptes : migration annulée pour ne rien écraser.")
        return
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    total = 0
    extra = sorted(t for t in have - set(MIGRATION_ORDER) if not t.startswith("sqlite_"))
    for table in MIGRATION_ORDER + extra:     # une table oubliee dans la liste est quand meme copiee
        if table not in have:
            continue
        pg_cols = {r[0] for r in dst.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                                             (table,))}
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
        cols = [c for c in rows[0].keys() if c in pg_cols]
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        sql += " ON CONFLICT DO NOTHING"
        for r in rows:
            dst.execute(sql, [r[c] for c in cols])
        if "id" in cols:
            dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
        total += len(rows)
        print(f"{table} : {len(rows)} ligne(s)")
    dst.commit()
    print(f"Migration terminée : {total} lignes copiées.")


@app.cli.command("compte-revue")
def review_accounts_cli():
    """Comptes pour les testeurs d'Apple et de Google : chantier de démonstration rempli, utilisable de n'importe où.
    Mots de passe neufs à chaque lancement ; à relancer après la revue pour les changer."""
    from services import demo as DEMO
    db = connect()
    if not db.execute("SELECT 1 FROM users WHERE email = 'aminata@demo.chantiervrai.ci'").fetchone():
        db.close()
        demo_cli.callback(force=True)
        db = connect()
    out = []
    # Le mot de passe public de la démonstration ne doit jamais ouvrir un compte sur le serveur en ligne.
    for r in db.execute("SELECT id FROM users WHERE email LIKE '%@demo.chantiervrai.ci'").fetchall():
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(secrets.token_urlsafe(24)), r["id"]))
    for email, label in (("aminata@demo.chantiervrai.ci", "Propriétaire"), ("koffi@demo.chantiervrai.ci", "Chef de chantier")):
        pw = "Revue-" + secrets.token_urlsafe(9)
        db.execute("UPDATE users SET password_hash = ?, totp_on = 0, totp_secret = NULL, blocked = 0, "
                   "session_version = session_version + 1 WHERE email = ?", (generate_password_hash(pw), email))
        out.append((label, email, pw))
    # Les testeurs ne sont pas sur le terrain : zone du chantier de démonstration élargie à toute la planète.
    db.execute("UPDATE projects SET radius = 20000000 WHERE owner_id = (SELECT id FROM users WHERE email = 'aminata@demo.chantiervrai.ci')")
    db.commit()
    db.close()
    print("Comptes à indiquer dans App Store Connect (Informations pour la revue) et Google Play Console (Accès à l'application) :")
    for label, email, pw in out:
        print(f"  {label:18} {email}   mot de passe : {pw}")
    print("Après la revue, relancez cette commande pour changer les mots de passe.")


@app.cli.command("demo")
@click.option("--force", is_flag=True, help="Ajouter les donnees meme si la base contient deja des comptes.")
def demo_cli(force):
    """Cree des comptes et des chantiers de demonstration (demonstrations commerciales, captures d'ecran)."""
    from services import demo as DEMO
    with app.test_request_context():
        db = connect()
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] and not force:
            print("La base contient deja des comptes. Utilisez --force pour ajouter quand meme la demonstration.")
            return
        g.lang = "fr"
        now = datetime.now(timezone.utc)
        ago = lambda days, hours=0: (now - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")
        pw = generate_password_hash(DEMO.PASSWORD)

        def user(name, email, role, phone="", lang="fr", **extra):
            cur = db.execute("INSERT INTO users (name, email, phone, password_hash, role, created_at, terms_at, lang, zone, "
                             "tarif, bio, verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (name, email, phone, pw, role, ago(80), ago(80), lang, extra.get("zone"),
                              extra.get("tarif"), extra.get("bio"), 1 if role == "inspecteur" else 0))
            return cur.lastrowid
        own = user("Aminata Koné", "aminata@demo.chantiervrai.ci", "proprio", "+33 6 12 34 56 78")
        chef = user("Koffi Yao", "koffi@demo.chantiervrai.ci", "chef", "07 08 09 10 11")
        insp = user("Awa Diallo", "awa@demo.chantiervrai.ci", "inspecteur", "05 06 07 08 09", zone="Abidjan, Bingerville",
                    tarif=45000, bio="Ingénieure génie civil, 12 ans de suivi de chantiers résidentiels.")
        steps = [(n, a, dd) for n, a, dd in DEFAULT_STEPS]
        pid = create_project(db, own, "Villa R+1 à Bingerville", "Bingerville, Abidjan", 5.3521, -3.8892, 100, steps,
                             (now - timedelta(days=72)).date().isoformat(),
                             pay_mode="sequestre" if escrow_enabled(db) else "suivi", require_app_capture=1)
        demo_escrow = escrow_enabled(db)
        # Abonnement de demonstration : offre Pro payee, en cours
        owner_row = db.execute("SELECT * FROM users WHERE id = ?", (own,)).fetchone()
        get_sub(db, owner_row)
        inv_id = create_invoice(db, owner_row, "pro", "mois", now - timedelta(days=10))
        invoice_paid(db, db.execute("SELECT * FROM billing_invoices WHERE id = ?", (inv_id,)).fetchone(), "mobile_money",
                     "SIM-ABO-DEMO")
        db.execute("UPDATE projects SET chef_id = ?, created_at = ? WHERE id = ?", (chef, ago(75), pid))
        st = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (pid,)).fetchall()
        plan = [("paye", 72, 44, 43), ("paye", 43, 24, 23), ("declare", 23, 1, None)]
        for (status, start, declared, paid), s_ in zip(plan, st):
            db.execute("UPDATE steps SET status = ?, started_at = ?, declared_at = ?, paid_at = ?, pay_ref = ? WHERE id = ?",
                       (status, ago(start), ago(declared), ago(paid) if paid else None,
                        f"SIM-V-DEMO{s_['position']}" if paid else None, s_["id"]))
        db.execute("UPDATE steps SET status = 'attente', started_at = NULL WHERE project_id = ? AND position > 2", (pid,))
        seed = 0
        for i, s_ in enumerate(st[:3]):
            for k in range(3):
                seed += 1
                img = DEMO.site_photo(i if i < 2 else 2, seed)
                name = save_image(img, UPLOAD_DIR)
                f = VISION.features(img)
                created = ago(plan[i][1] - 4 - k * 5, k)
                db.execute("INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, note, created_at, device_lat, "
                           "device_lng, device_acc, distance, ok, reasons, kind, source, feat, ai_status, capture) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, s_["id"], chef, name, secrets.token_hex(32), ["Façade nord", "Angle sud-est",
                            "Vue d'ensemble"][k], created, 5.3521 + 0.0001 * k, -3.8891, 6, 8 + 4 * k, 1, "", "photo", "chef",
                            json.dumps(f), "off", "app"))
        img = DEMO.site_photo(3, 99)
        db.execute("INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, note, created_at, device_lat, device_lng, "
                   "distance, ok, reasons, kind, source, ai_status, capture) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (pid, st[2]["id"], chef, save_image(img, UPLOAD_DIR), secrets.token_hex(32), "Dalle",
                    ago(3), 5.3712, -3.9010, 2380, 0,
                    I18N.store_list([L("Prise à %(distance)s m du terrain (limite %(radius)s m)", distance=2380, radius=100)]),
                    "photo", "chef", "off", "app"))
        for kind, amount, days in (("depot", 9000000, 70), ("versement", 3000000, 43), ("versement", 2500000, 23)):
            if not demo_escrow:
                break
            db.execute("INSERT INTO transactions (project_id, user_id, kind, amount, provider, ref, status, created_at, "
                       "updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (pid, own, kind, amount, "simulation", tx_ref(pid),
                                                                   "reussi", ago(days), ago(days)))
        db.execute("INSERT INTO inspections (project_id, step_id, inspector_id, requested_by, fee, status, verdict, report, "
                   "created_at, done_at, paid) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (pid, st[1]["id"], insp, own, 45000, "realisee", "conforme",
                    "Soubassement conforme au plan. Chaînages en place, arases de niveau. RAS.", ago(26), ago(24), 1))
        # Controle qualite de demonstration : ferraillage de la dalle basse, mesures saisies par le chef
        q = db.execute("INSERT INTO quality_reviews (project_id, step_id, ouvrage, label, lang, measures, measures_by, measures_at, "
                       "created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pid, st[2]["id"], "ferraillage", "Dalle basse", "fr",
                        json.dumps({"espacement": "15 15 16 22 15", "enrobage": "2"}), chef, ago(2), own, ago(4)))
        demo_rid = q.lastrowid
        for shot_id, pr in zip(("ensemble", "cadres", "cales"), db.execute(
                "SELECT id FROM proofs WHERE step_id = ? AND ok = 1 ORDER BY id", (st[2]["id"],)).fetchall()):
            db.execute("INSERT INTO quality_photos (review_id, proof_id, shot, created_at) VALUES (?,?,?,?)",
                       (demo_rid, pr["id"], shot_id, ago(3)))
        if not demo_escrow:
            for s_, days, ref in ((st[0], 43, "WAVE-TX-48213"), (st[1], 23, "OM-TX-90577")):
                db.execute("INSERT INTO payment_records (project_id, kind, ref_id, payer_id, payee_id, amount, method, reference, "
                           "paid_on, status, created_at, answered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, "etape", s_["id"], own, chef, s_["amount"], "mobile_money", ref, ago(days)[:10], "confirme",
                            ago(days), ago(days - 1)))
                db.execute("UPDATE steps SET pay_ref = ? WHERE id = ?", (ref, s_["id"]))
            db.execute("INSERT INTO payment_records (project_id, kind, ref_id, payer_id, payee_id, amount, method, reference, "
                       "paid_on, status, created_at, answered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, "inspection", db.execute("SELECT id FROM inspections WHERE project_id = ?", (pid,)).fetchone()[0],
                        own, insp, 45000, "mobile_money", "WAVE-TX-51102", ago(24)[:10], "confirme", ago(24), ago(23)))
        for days, text in ((72, L("Chantier créé")), (70, L("%(amount)s FCFA déposés sur le séquestre%(sim)s",
                           amount="9 000 000", sim="") if demo_escrow else L("Mode de paiement : ") + PAY_MODE_LOG["suivi"]), (44, L("Étape « %(name)s » déclarée terminée", name=st[0]["name"])),
                           (43, L("Étape « %(name)s » validée et payée", name=st[0]["name"])),
                           (24, L("Rapport d'inspection : %(v)s", v=L("Conforme"))),
                           (23, L("Étape « %(name)s » validée et payée", name=st[1]["name"])),
                           (3, L("Preuve refusée") + L(" pour « %(name)s »", name=st[2]["name"])),
                           (1, L("Étape « %(name)s » déclarée terminée", name=st[2]["name"]))):
            db.execute("INSERT INTO activity (project_id, user_id, text, created_at) VALUES (?,?,?,?)",
                       (pid, chef if "déclarée" in getattr(text, "msg", "") else own, I18N.store(text), ago(days)))
        notify(pid, [own], L("Étape à valider"),
               L("Le chef de chantier déclare « %(name)s » terminée (%(ok_ct)s). Vérifiez avant de payer.",
                 name=st[2]["name"], ok_ct="3 preuves vérifiées"), f"/chantiers/{pid}?onglet=etapes", db=db)
        # Plan de financement de demonstration : diaspora, revenus en euros, credit et transferts
        db.execute("INSERT INTO fin_profiles (project_id, monthly_income, income_currency, other_charges, employer, country, diaspora, "
                   "updated_at) VALUES (?,?,?,?,?,?,?,?)", (pid, 3200, "EUR", 450, "Hôpital Lariboisière", "France", 1, ago(70)))
        start = now - timedelta(days=72)
        for kind, label, lender, amount, when, months, rate, status, got in (
                ("epargne", "Épargne personnelle", None, 6000000, start, None, None, "confirmee", [(start, 6000000)]),
                ("transferts", "Virements mensuels depuis Paris", None, 450000, start, 18, None, "confirmee",
                 [(start + timedelta(days=30 * k), 450000) for k in range(3)]),
                ("credit", "Prêt habitat", "Banque partenaire (à choisir)", 9000000, now + timedelta(days=75), 120, 8.5, "prevue", []),
                ("famille", "Aide du frère aîné", "Ibrahim Koné", 1500000, now - timedelta(days=10), None, None, "confirmee", [])):
            cur = db.execute("INSERT INTO fin_sources (project_id, kind, label, lender, amount, expected_on, months, rate, status, created_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, kind, label, lender, amount, when.date().isoformat(), months, rate, status, ago(71)))
            for d_, a_ in got:
                db.execute("INSERT INTO fin_receipts (source_id, project_id, amount, received_on, created_by, created_at) VALUES (?,?,?,?,?,?)",
                           (cur.lastrowid, pid, a_, d_.date().isoformat(), own, ago(70)))
        db.execute("INSERT INTO fin_costs (project_id, label, amount, due_on, paid, created_at) VALUES (?,?,?,?,?,?)",
                   (pid, "Titre foncier et notaire", 1200000, (now - timedelta(days=70)).date().isoformat(), 1, ago(71)))
        # Terrain de demonstration : ACD, bornes du geometre, verifications en cours
        db.execute("INSERT INTO land_files (project_id, doc_type, title_ref, holder_name, seller_name, area_declared, bornes, checks, "
                   "updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (pid, "acd", "ACD n° 2019-0457", "Aminata Koné", "Aminata Koné", 600,
                    "5.35199, -3.88932\n5.35199, -3.88910\n5.35221, -3.88910\n5.35221, -3.88932",
                    json.dumps({"vendeur": True, "geometre": True, "notaire": True, "voisinage": True}), own, ago(80)))
        # Plan et realite : elements a compter
        for label, exp, decl, st_ in ((I18N.store(L("Fenêtres")), 8, 8, "ok"), (I18N.store(L("Portes")), 6, None, "a_faire"),
                                      ("Poteaux du rez-de-chaussée", 12, 10, "ecart")):
            db.execute("INSERT INTO plan_items (project_id, label, expected, source, declared, declared_by, status, note, created_by, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, label, exp, "manuel", decl, chef if decl is not None else None, st_,
                                                        "2 poteaux à couler la semaine prochaine" if st_ == "ecart" else None, own, ago(5)))
        # Notes du chef recues par WhatsApp
        for days, kind, text, summ, cat, urgent in (
                (6, "vocal", "Bonjour madame, on a fini le ferraillage de la dalle basse, on attend le contrôle d'Awa mardi pour couler mercredi.",
                 "Ferraillage de la dalle basse terminé ; coulage prévu mercredi après le contrôle de mardi.", "avancement", 0),
                (2, "vocal", "Il nous manque vingt sacs de ciment pour finir la dalle, il faut commander avant jeudi sinon on arrête.",
                 "Il manque 20 sacs de ciment pour finir la dalle : commande à passer avant jeudi.", "materiaux", 1),
                (1, "texte", "Le ferrailleur repasse demain pour reprendre les cales sous la dalle.", None, None, 0)):
            db.execute("INSERT INTO site_notes (project_id, user_id, step_id, channel, kind, transcript, summary, category, urgent, status, "
                       "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pid, chef, st[2]["id"], "whatsapp", kind, text, summ or text, cat, urgent,
                                                                       "pret", ago(days)))
        db.commit()
        run_quality_analysis(demo_rid, False)
        save_report(db, db.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone())
        # Chantier public pour le portail citoyen
        steps2 = [(n, round(185000000 * share), dd) for n, share, dd in PUBLIC_STEPS]
        pid2 = create_project(db, own, "Groupe scolaire de 6 classes", "Bingerville, quartier Santé", 5.3540, -3.8850, 300,
                              steps2, (now - timedelta(days=60)).date().isoformat(), kind="public",
                              market={"marche_ref": "2026-0-1-0123/02-12", "autorite": "Mairie de Bingerville",
                                      "attributaire": "BTP Lagunes SARL", "montant_marche": 185000000, "is_public": True})
        st2 = db.execute("SELECT * FROM steps WHERE project_id = ? ORDER BY position", (pid2,)).fetchall()
        db.execute("UPDATE projects SET chef_id = ?, description = ? WHERE id = ?",
                   (chef, "Six salles de classe, un bloc administratif et des latrines.", pid2))
        db.execute("UPDATE steps SET status = 'paye', started_at = ?, declared_at = ?, paid_at = ? WHERE id = ?",
                   (ago(60), ago(41), ago(40), st2[0]["id"]))
        db.execute("UPDATE steps SET status = 'en_cours', started_at = ? WHERE id = ?", (ago(40), st2[1]["id"]))
        for k in range(3):
            img = DEMO.site_photo(k, 200 + k)
            name = save_image(img, UPLOAD_DIR)
            pub, _n, _ok = VISION.blur_faces(img)
            db.execute("INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, created_at, distance, ok, reasons, "
                       "kind, source, ai_status, capture, is_published, public_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid2, st2[min(k, 1)]["id"], chef, name, secrets.token_hex(32), ago(50 - k * 10),
                        20, 1, "", "photo", "chef", "off", "app", 1, save_image(pub, UPLOAD_DIR, prefix="pub_")))
        # Fournisseur verifie, son catalogue et une commande livree, comptee et payee
        sup = user("Quincaillerie du Carrefour", "quincaillerie@demo.chantiervrai.ci", "fournisseur", "01 02 03 04 05",
                   zone="Bingerville, Cocody", bio="Ciment, fer, agrégats. Dépôt au carrefour de la mairie de Bingerville.")
        db.execute("UPDATE users SET verified = 1, supplier_terms_at = ? WHERE id = ?", (ago(79), sup))
        prods = {}
        for name, unit, price in [("Ciment CPJ 42,5 (sac de 50 kg)", "sac", 5400), ("Fer à béton HA 10 (barre de 12 m)", "barre", 4100),
                                  ("Fer à béton HA 8 (barre de 12 m)", "barre", 2700), ("Sable lagunaire", "voyage", 85000),
                                  ("Gravier 5/15", "voyage", 115000), ("Parpaing creux de 15", "unité", 450)]:
            prods[name] = db.execute("INSERT INTO products (supplier_id, material, name, unit, price, created_at) "
                                     "VALUES (?,?,?,?,?,?)", (sup, MAT.normalize(name), name, unit, price, ago(70))).lastrowid
        oid = db.execute("INSERT INTO orders (ref, project_id, step_id, supplier_id, created_by, status, pay_mode, total, "
                         "received_total, commission, created_at, updated_at, delivered_at, received_at, delivery_date) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("CMD-DEMO-0001", pid, st[1]["id"], sup, chef, "receptionnee", "sequestre" if demo_escrow else "suivi",
                          120 * 5400 + 60 * 4100,
                          115 * 5400 + 60 * 4100, round((115 * 5400 + 60 * 4100) * commission_pct() / 100), ago(40),
                          ago(37), ago(38), ago(37), ago(38)[:10])).lastrowid
        for name, q, qr in [("Ciment CPJ 42,5 (sac de 50 kg)", 120, 115), ("Fer à béton HA 10 (barre de 12 m)", 60, 60)]:
            pr_ = db.execute("SELECT * FROM products WHERE id = ?", (prods[name],)).fetchone()
            db.execute("INSERT INTO order_lines (order_id, product_id, material, name, unit, qty, unit_price, qty_received) "
                       "VALUES (?,?,?,?,?,?,?,?)", (oid, pr_["id"], pr_["material"], name, pr_["unit"], q, pr_["price"], qr))
        if demo_escrow:
            db.execute("INSERT INTO transactions (project_id, user_id, kind, amount, provider, ref, provider_ref, status, "
                       "created_at, updated_at, order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, own, "versement", 115 * 5400 + 60 * 4100, "simulation", "CV-DEMO-CMD1", "SIM-V-CMD1", "reussi",
                        ago(37), ago(37), oid))
        else:
            db.execute("INSERT INTO payment_records (project_id, kind, ref_id, payer_id, payee_id, amount, method, reference, "
                       "paid_on, status, created_at, answered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, "commande", oid, own, sup, 115 * 5400 + 60 * 4100, "virement", "VIR-2026-0412", ago(37)[:10],
                        "confirme", ago(37), ago(36)))
        o_ = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        order_invoice(db, o_, order_lines(oid, db), db.execute("SELECT * FROM users WHERE id = ?", (sup,)).fetchone())
        db.execute("UPDATE invoices SET created_at = ? WHERE media_type = 'commande'", (ago(37),))
        # Prevu des materiaux, stock, controleur habilite et controles techniques
        for s_, rows in ((st[1], [("Ciment", "sac", 120), ("Fer à béton", "barre", 60)]),
                         (st[2], [("Ciment", "sac", 95), ("Sable", "m³", 6), ("Gravier", "m³", 11.5), ("Fer à béton", "barre", 80)])):
            for mat, unit, q in rows:
                db.execute("INSERT INTO materials_plan (project_id, step_id, material, unit, qty_planned, unit_price_ref) "
                           "VALUES (?,?,?,?,?,?)", (pid, s_["id"], mat, unit, q, {"Ciment": 5200, "Fer à béton": 4000}.get(mat)))
        for mat, unit, q, kind, step_i, days, note in (
                ("Ciment", "sac", 115, "entree", 1, 37, "CMD-DEMO-0001"), ("Fer à béton", "barre", 60, "entree", 1, 37, "CMD-DEMO-0001"),
                ("Ciment", "sac", 104, "sortie", 1, 30, "Soubassement"), ("Fer à béton", "barre", 58, "sortie", 1, 30, None),
                ("Ciment", "sac", 90, "entree", 2, 12, "BL 2291 Quincaillerie du Carrefour"),
                ("Ciment", "sac", 82, "sortie", 2, 4, "Coulage de la dalle basse")):
            db.execute("INSERT INTO stock_moves (project_id, step_id, material, unit, qty, kind, source, order_id, note, user_id, "
                       "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pid, st[step_i]["id"], mat, unit, q, kind,
                                                                       "commande" if note == "CMD-DEMO-0001" else "manuel",
                                                                       oid if note == "CMD-DEMO-0001" else None, note, chef, ago(days)))
        db.execute("INSERT INTO stock_thresholds (project_id, material, min_qty) VALUES (?,?,?)", (pid, "Ciment", 20))
        db.execute("INSERT INTO project_members (project_id, user_id, role, created_at) VALUES (?,?,?,?)",
                   (pid, insp, "controleur", ago(60)))
        for i, s_ in enumerate(st[:3]):
            for k, (name, req, kind, minv, unit) in enumerate(checks_for_step(s_["name"])):
                done = i < 2 or k < 2
                value = (27.5 if i < 2 else None) if kind == "essai" else None
                db.execute("INSERT INTO step_checks (project_id, step_id, name, required, kind, min_value, unit, status, value, "
                           "note, checked_by, checked_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, s_["id"], I18N.store(L(name)), req, kind, minv, unit,
                            "conforme" if done and (kind != "essai" or value) else "a_faire", value,
                            ("Conforme au plan de ferraillage." if "ferraillage" in name else None) if done else None,
                            insp if done and (kind != "essai" or value) else None,
                            ago([46, 25, 2][i], k) if done and (kind != "essai" or value) else None, ago(70)))
            db.execute("UPDATE steps SET checks_init = 1 WHERE id = ?", (s_["id"],))
        # Fiche du projet, parcelle, architecte, maquette IFC en deux versions, capteurs
        parcel = [[5.35228, -3.88942], [5.35229, -3.88898], [5.35192, -3.88896], [5.35191, -3.88941]]
        db.execute("UPDATE projects SET building_type = 'immeuble', levels = 1, surface_land = 600, surface_floor = 240, "
                   "land_title = 'ACD n° 2019-0457', land_ref = 'Lot 24, îlot 7', commune = 'Bingerville', "
                   "permit_ref = 'PC 0812/2026', parcel = ? WHERE id = ?", (json.dumps(parcel), pid))
        arch = user("Yao Kouassi", "architecte@demo.chantiervrai.ci", "pro", "07 11 22 33 44")
        db.execute("UPDATE users SET profession = 'architecte' WHERE id = ?", (arch,))
        db.execute("INSERT INTO project_members (project_id, user_id, role, created_at) VALUES (?,?,?,?)", (pid, arch, "architecte", ago(72)))
        for version, extra, days, note in ((1, 0, 70, "Permis de construire"), (2, 2, 20, "Deux poteaux ajoutés pour la terrasse de l'étage")):
            raw = IFC.sample(2, extra_columns=extra, name="Villa R+1 à Bingerville")
            fname = f"{secrets.token_hex(12)}.ifc"
            with open(os.path.join(BIM_DIR, fname), "w", encoding="utf-8") as fh:
                fh.write(raw)
            db.execute("INSERT INTO bim_models (project_id, user_id, version, filename, original_name, summary, note, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (pid, arch, version, fname, f"villa-v{version}.ifc",
                                                    json.dumps(IFC.parse(raw), ensure_ascii=False), note, ago(days)))
        for storey, step_i in (("Fondations", 0), ("Rez-de-chaussée", 1), ("Étage 1", 2)):
            db.execute("INSERT INTO bim_storeys (project_id, storey, step_id) VALUES (?,?,?)", (pid, storey, st[step_i]["id"]))
        db.execute("UPDATE users SET company = 'Bâtir Plus SARL, RCCM CI-ABJ-2019-B-4471', zone = 'Bingerville, Cocody', "
                   "bio = '12 ans de gros œuvre : villas et immeubles R+2. Références sur demande.', verified = 1, "
                   "verify_requested = 1 WHERE id = ?", (chef,))
        db.execute("INSERT INTO contractor_reviews (project_id, author_id, contractor_id, rating, comment, created_at) VALUES "
                   "(?,?,?,?,?,?)", (pid, own, chef, 4, "Sérieux et joignable. Photos envoyées chaque semaine ; un retard de "
                                                       "10 jours sur le soubassement, rattrapé ensuite.", ago(20)))
        db.execute("INSERT INTO plan_readings (project_id, user_id, doc_id, result, created_at) VALUES (?,?,?,?,?)",
                   (pid, arch, None, json.dumps({"scale": "1/100", "levels": 1, "rooms": [
                       {"name": "Séjour", "area": 32.5}, {"name": "Cuisine", "area": 11.2}, {"name": "Chambre 1", "area": 14.0},
                       {"name": "Chambre 2", "area": 12.6}, {"name": "Salle d'eau", "area": 5.8}, {"name": "Dégagement", "area": 8.1}],
                       "floor_area": 84.2, "ext_walls": 38.4, "int_walls": 27.6, "height": 2.8, "doors": 7, "windows": 8,
                       "confidence": 0.82, "remarks": "Cotes du séjour partiellement masquées par un texte.", "source": "ia"},
                       ensure_ascii=False), ago(30)))
        # Zones depuis la maquette, quantites prevues et posees, visites 360
        zone_ids = {}
        for pos, (storey, step_i) in enumerate((("Fondations", 0), ("Rez-de-chaussée", 1), ("Étage 1", 2), ("Toiture", 5))):
            zone_ids[storey] = db.execute("INSERT INTO zones (project_id, name, kind, storey, position, created_at) VALUES (?,?,?,?,?,?)",
                                          (pid, storey, "etage", storey, pos + 1, ago(60))).lastrowid
        db.execute("UPDATE proofs SET zone_id = ? WHERE project_id = ? AND step_id = ?", (zone_ids["Fondations"], pid, st[0]["id"]))
        db.execute("UPDATE proofs SET zone_id = ? WHERE project_id = ? AND step_id = ?", (zone_ids["Rez-de-chaussée"], pid, st[1]["id"]))
        db.execute("UPDATE proofs SET zone_id = ? WHERE project_id = ? AND step_id = ?", (zone_ids["Étage 1"], pid, st[2]["id"]))
        summary = json.loads(db.execute("SELECT summary FROM bim_models WHERE project_id = ? ORDER BY version DESC", (pid,)).fetchone()[0])
        last_proof = {r["step_id"]: r["id"] for r in db.execute("SELECT step_id, MAX(id) AS id FROM proofs WHERE project_id = ? AND ok = 1 "
                                                                "GROUP BY step_id", (pid,))}
        for storey, step_i, done_share, pending in (("Fondations", 0, 1.0, 0), ("Rez-de-chaussée", 1, 1.0, 0), ("Étage 1", 2, 0.6, 4)):
            for label, count in bim_items_for_zone(summary, storey).items():
                iid = db.execute("INSERT INTO work_items (project_id, zone_id, step_id, label, unit, qty_planned, source, created_at) "
                                 "VALUES (?,?,?,?,?,?,?,?)", (pid, zone_ids[storey], st[step_i]["id"], label, "u", count, "bim", ago(55))).lastrowid
                done = round(count * done_share) if label in ("Poteaux", "Fondations", "Poutres", "Dalles") or done_share == 1 else 0
                if done:
                    db.execute("INSERT INTO work_progress (item_id, qty, proof_id, status, user_id, validated_by, validated_at, created_at) "
                               "VALUES (?,?,?,?,?,?,?,?)", (iid, done, last_proof.get(st[step_i]["id"]), "valide", chef, own,
                                                            ago(30 - step_i * 10), ago(31 - step_i * 10)))
                if pending and label == "Poteaux":
                    db.execute("INSERT INTO work_progress (item_id, qty, proof_id, note, status, user_id, created_at) VALUES (?,?,?,?,?,?,?)",
                               (iid, pending, last_proof.get(st[step_i]["id"]), "Poteaux de la terrasse coulés hier", "declare", chef, ago(1)))
        for k, (stage, days) in enumerate(((1, 9), (2, 2))):
            img = DEMO.pano(stage, seed=k)
            name = save_image(img, PANO_DIR, 6000, prefix="pano_")
            th = save_image(img, PANO_DIR, 800, prefix="th_")
            change = None
            if k == 1:
                change = round(VISION.change_ratio(DEMO.pano(1, 0).resize((1024, 512)), img.resize((1024, 512))) * 100, 1)
            db.execute("INSERT INTO pano_visits (project_id, zone_id, user_id, filename, thumb, sha256, feat, lat, lng, distance, taken, ok, "
                       "change_pct, ai_note, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, zone_ids["Étage 1"], chef, name, th, secrets.token_hex(32), json.dumps(VISION.features(img)), 5.35212,
                        -3.88918, 3, ago(days), 1, change,
                        json.dumps({"progress": "Les murs en parpaings sont montés entre la moitié des poteaux de l'étage.",
                                    "changes": ["Murs en parpaings montés sur quatre travées", "Stock de matériaux déplacé"],
                                    "check": ["Aplomb des nouveaux murs", "Chaînage prévu en tête de mur"], "same_place": True},
                                   ensure_ascii=False) if k == 1 else None, None, ago(days)))
        rng = random.Random(7)
        for kind, name, unit, mn, mx, base, spread in (("humidite", "Humidité de la dalle basse (cure)", "%", 60, None, 78, 6),
                                                       ("deformation", "Fissuromètre mur nord", "mm", -2, 2, 0.4, 0.3),
                                                       ("pluie", "Pluviomètre du chantier", "mm", None, 30, 4, 6)):
            sid = db.execute("INSERT INTO sensors (project_id, kind, name, unit, token, min_value, max_value, created_at) "
                             "VALUES (?,?,?,?,?,?,?,?)", (pid, kind, name, unit, secrets.token_urlsafe(24), mn, mx, ago(12))).lastrowid
            last = None
            for h in range(36, 0, -1):
                v = round(max(0, base + rng.uniform(-spread, spread) - (h * 0.2 if kind == "humidite" else 0)), 2)
                db.execute("INSERT INTO sensor_readings (sensor_id, value, measured_at) VALUES (?,?,?)",
                           (sid, v, (datetime.now(timezone.utc) - timedelta(hours=h * 4)).isoformat(timespec="seconds")))
                last = v
            db.execute("UPDATE sensors SET last_value = ?, last_at = ? WHERE id = ?", (last, ago(0), sid))
        db.commit()
        db.close()
    print("Démonstration créée. Mot de passe de tous les comptes :", DEMO.PASSWORD)
    print("  Propriétaire  aminata@demo.chantiervrai.ci")
    print("  Chef          koffi@demo.chantiervrai.ci")
    print("  Inspectrice   awa@demo.chantiervrai.ci")
    print("  Fournisseur   quincaillerie@demo.chantiervrai.ci")
    print("  Architecte    architecte@demo.chantiervrai.ci")


def daily_tasks():
    """Tâche quotidienne complète : comptes rendus, satellite, relances, échéances, sauvegarde. Renvoie le compte rendu."""
    out = []
    db = connect()
    try:
        n = 0
        for p in db.execute("SELECT * FROM projects").fetchall():
            if report_due(db, p):
                save_report(db, p)
                n += 1
        out.append(f"{n} compte(s) rendu(s), {monthly_satellite(db)} image(s) satellite, {daily_weather(db)} relevé(s) météo.")
        out.append(retry_pending(db))
        out.append(f"Étapes sans réponse du propriétaire : {auto_validate_steps(db)}")
        out.append(f"{remind_payments(db)} relance(s) de paiement à confirmer.")
        out.append(f"Abonnements : {billing_daily(db)}")
        out.append(f"Litiges : {disputes_daily(db)}")
        out.append(f"Portail citoyen : {signalements_daily(db)}")
        out.append(f"Financement : {finance_daily(db)} alerte(s).")
        set_setting(db, "ops_daily_last", now_iso())
        db.commit()
    finally:
        db.close()
    out += backup_and_copy()
    return out


def retry_tasks():
    """Relances toutes les 5 minutes, et contrôle que la sauvegarde de la nuit a bien eu lieu."""
    db = connect()
    try:
        out = [retry_pending(db)]
        late = backup_age_hours(db)
        if late is not None and late > 36:
            alert_team("Sauvegarde en retard", f"Dernière sauvegarde réussie il y a {int(late)} h.", "backup_late",
                       every_minutes=12 * 60, db=db)
            out.append(f"Sauvegarde en retard : {int(late)} h")
        return out
    finally:
        db.close()


def backup_age_hours(db):
    """Heures depuis la dernière sauvegarde réussie (None si aucune encore : nouveau serveur)."""
    last = get_setting("ops_backup_last", None, db)
    if not last:
        return None
    try:
        t = datetime.fromisoformat(last)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


@app.cli.command("quotidien")
def daily_cli():
    """Tache quotidienne complete : comptes rendus, satellite, relances, sauvegarde."""
    with app.test_request_context():
        for line in daily_tasks():
            print(line)


# --------------------------------------------------------------------------
# Tâches lancées par un planificateur externe (Render Cron Job, GitHub Actions…)
# --------------------------------------------------------------------------
TASKS = {"relancer": retry_tasks, "quotidien": daily_tasks, "sauvegarde": backup_and_copy}
TASK_LOCK_MINUTES = {"relancer": 10, "quotidien": 180, "sauvegarde": 180}


def run_task(name):
    """Lance une tâche une seule fois à la fois, même avec plusieurs serveurs (verrou en base)."""
    db = connect()
    try:
        key = "lock_" + name
        cur = get_setting(key, None, db)
        now = datetime.now(timezone.utc)
        if cur:
            try:
                if now - datetime.fromisoformat(cur) < timedelta(minutes=TASK_LOCK_MINUTES[name]):
                    return False
            except ValueError:
                pass
        set_setting(db, key, now.isoformat())
        db.commit()
    finally:
        db.close()

    def work():
        with app.test_request_context():
            try:
                for line in TASKS[name]():
                    app.logger.info("[%s] %s", name, line)
            except Exception as e:  # signale et libère
                app.logger.exception("tâche %s", name)
                alert_team(f"Tâche « {name} » en échec", repr(e)[:500], "task_" + name, every_minutes=6 * 60)
            finally:
                d = connect()
                set_setting(d, "lock_" + name, "")
                set_setting(d, "ops_task_" + name, now_iso())
                d.commit()
                d.close()
    run_async(work)
    return True


@app.route("/taches/<name>", methods=["POST"])
def run_task_route(name):
    """Point d'entrée du planificateur : POST avec « Authorization: Bearer <CRON_TOKEN> »."""
    token = env("CRON_TOKEN")
    given = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, given):
        abort(403)
    if name not in TASKS:
        abort(404)
    started = run_task(name)
    return jsonify(task=name, started=started, note=None if started else "déjà en cours"), (202 if started else 200)


@app.route("/sante")
def health():
    """État du service, pour l'hébergeur (contrôle de santé) et un service de surveillance externe.
    Code 200 tant que l'application et la base répondent ; les retards de sauvegarde sont signalés sans faire
    redémarrer le service."""
    out, ok = {"application": "ok"}, True
    try:
        db = connect()
        db.execute("SELECT 1").fetchone()
        out["base"] = "postgresql" if DB.is_pg() else "sqlite"
        age = backup_age_hours(db)
        out["sauvegarde_heures"] = None if age is None else round(age, 1)
        out["sauvegarde_ok"] = get_setting("ops_backup_ok", None, db) == "1" if age is not None else None
        out["copie_distante"] = ("non configurée" if not OFFSITE.configured() else
                                 "ok" if get_setting("ops_offsite_ok", None, db) == "1" else
                                 "échec" if get_setting("ops_offsite_ok", None, db) == "0" else "pas encore faite")
        db.close()
    except Exception as e:  # base injoignable
        ok, out["base"] = False, "injoignable : " + str(e)[:120]
    try:
        test = os.path.join(UPLOAD_DIR, ".sante")
        with open(test, "w") as fh:
            fh.write(now_iso())
        os.remove(test)
        free = shutil.disk_usage(UPLOAD_DIR).free
        out["disque_libre_go"] = round(free / 1e9, 1)
        out["disque"] = "ok" if free > 500e6 else "presque plein"
    except OSError as e:
        ok, out["disque"] = False, "écriture impossible : " + str(e)[:120]
    out["alerte"] = bool(out.get("sauvegarde_heures") and out["sauvegarde_heures"] > 36) or out.get("copie_distante") == "échec" \
        or out.get("disque") == "presque plein"
    out["statut"] = "ok" if ok else "panne"
    resp = jsonify(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp, (200 if ok else 503)


@got_request_exception.connect_via(app)
def _alert_on_error(sender, exception, **extra):
    """Erreur serveur : l'équipe est prévenue (au plus une fois par heure pour une même erreur)."""
    try:
        where = f"{request.method} {request.path}"
    except RuntimeError:
        where = "?"
    kind = type(exception).__name__
    try:
        alert_team(f"Erreur serveur ({kind})", f"{where}\n{str(exception)[:400]}", "err_" + kind + "_" + where[:60],
                   every_minutes=60)
    except Exception:  # l'alerte ne doit jamais aggraver la panne
        app.logger.exception("alerte impossible")


@app.route("/chantiers/<int:project_id>/rapports", methods=["GET", "POST"])
@login_required
def reports(project_id):
    p = load_project(project_id, roles=("owner",))
    db = get_db()
    if request.method == "POST":
        rid = save_report(db, p)
        return redirect(url_for("report", project_id=project_id, report_id=rid))
    rows = db.execute("SELECT * FROM reports WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    items = [(r, json.loads(r["content"])) for r in rows]
    activity = db.execute(
        "SELECT activity.*, users.name AS author FROM activity LEFT JOIN users ON users.id = activity.user_id "
        "WHERE project_id = ? ORDER BY activity.id DESC LIMIT 200", (project_id,)).fetchall()
    return render_template("reports.html", p=p, items=items, activity=activity)


@app.route("/chantiers/<int:project_id>/rapports/<int:report_id>")
@login_required
def report(project_id, report_id):
    p = load_project(project_id, roles=("owner",))
    r = get_db().execute("SELECT * FROM reports WHERE id = ? AND project_id = ?", (report_id, project_id)).fetchone()
    if r is None:
        abort(404)
    return render_template("report.html", p=p, r=r, c=json.loads(r["content"]))


# --------------------------------------------------------------------------
# Carte de tous les chantiers
# --------------------------------------------------------------------------
def map_points(projects, db, public=False):
    pts = []
    for p in projects:
        s = project_stats(p["id"], db)
        pred = project_prediction(p, s, db)
        pts.append({
            "id": p["id"], "name": p["name"], "address": p["address"] or "", "lat": p["lat"], "lng": p["lng"],
            "pct": s["verified_pct"], "risk": pred["risk"] if pred else "inconnu",
            "delay": pred["delay"] if pred else None, "kind": p["kind"],
            "current": s["current"]["name"] if s["current"] else "Terminé",
            "url": url_for("portal_project", project_id=p["id"]) if public else url_for("project", project_id=p["id"]),
            "to_validate": s["to_validate"],
        })
    pts.sort(key=lambda q: q["delay"] if q["delay"] is not None and q["risk"] != "terminé" else -9999, reverse=True)
    return pts


@app.route("/carte")
@login_required
def map_view():
    db = get_db()
    pts = map_points(user_projects(current_user()), db)
    return render_template("map.html", points=pts, public=False)


# --------------------------------------------------------------------------
# Portail citoyen (sans connexion)
# --------------------------------------------------------------------------
def public_project(project_id):
    p = get_db().execute("SELECT * FROM projects WHERE id = ? AND kind = 'public' AND is_public = 1",
                         (project_id,)).fetchone()
    if p is None:
        abort(404)
    return p


@app.route("/portail")
def portal():
    db = get_db()
    q = request.args.get("q", "").strip()
    projects = db.execute("SELECT * FROM projects WHERE kind = 'public' AND is_public = 1 ORDER BY id DESC").fetchall()
    if q:
        pq = plain(q)
        projects = [p for p in projects if pq in plain(" ".join(str(p[k] or "") for k in
                                                                 ("name", "address", "autorite", "attributaire",
                                                                  "marche_ref")))]
    pts = map_points(projects, db, public=True)
    return render_template("portal.html", points=pts, q=q)


@app.route("/portail/<int:project_id>")
def portal_project(project_id):
    p = public_project(project_id)
    db = get_db()
    s = project_stats(project_id)
    pred = project_prediction(p, s)
    photos = db.execute("SELECT proofs.*, steps.name AS step_name FROM proofs JOIN steps ON steps.id = proofs.step_id "
                        "WHERE proofs.project_id = ? AND ok = 1 AND is_published = 1 ORDER BY proofs.id DESC LIMIT 24",
                        (project_id,)).fetchall()
    docs = db.execute("SELECT * FROM documents WHERE project_id = ? AND is_public = 1 ORDER BY id DESC",
                      (project_id,)).fetchall()
    sigs = db.execute("SELECT * FROM signalements WHERE project_id = ? AND hidden = 0 ORDER BY id DESC LIMIT 20",
                      (project_id,)).fetchall()
    insp = db.execute("SELECT i.verdict, i.done_at, st.name AS step_name FROM inspections i LEFT JOIN steps st "
                      "ON st.id = i.step_id WHERE i.project_id = ? AND i.status = 'realisee' ORDER BY i.id DESC",
                      (project_id,)).fetchall()
    return render_template("portal_project.html", p=p, s=s, pred=pred, photos=photos, docs=docs, sigs=sigs, insp=insp,
                           schedule=PRED.step_schedule(p, s["steps"]))


@app.route("/portail/photos/<int:proof_id>")
def portal_photo(proof_id):
    pr = get_db().execute("SELECT * FROM proofs WHERE id = ? AND ok = 1 AND is_published = 1 AND public_file IS NOT NULL",
                          (proof_id,)).fetchone()
    if pr is None:
        abort(404)
    public_project(pr["project_id"])
    return send_from_directory(UPLOAD_DIR, pr["public_file"])


@app.route("/portail/documents/<int:doc_id>")
def portal_document(doc_id):
    doc = get_db().execute("SELECT * FROM documents WHERE id = ? AND is_public = 1", (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    public_project(doc["project_id"])
    return send_document(doc)


@app.route("/portail/<int:project_id>/signaler", methods=["POST"])
def portal_report(project_id):
    p = public_project(project_id)
    db = get_db()
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]).strip()
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    if db.execute("SELECT COUNT(*) FROM signalements WHERE ip = ? AND created_at >= ?", (ip, hour_ago)).fetchone()[0] >= 5:
        flash(_('Trop de signalements envoyés. Réessayez plus tard.'), "error")
        return redirect(url_for("portal_project", project_id=project_id))
    text = request.form.get("text", "").strip()
    if len(text) < 10:
        flash(_('Décrivez le problème (10 caractères minimum).'), "error")
        return redirect(url_for("portal_project", project_id=project_id))
    lat, lng = to_float(request.form.get("lat")), to_float(request.form.get("lng"))
    dist = round(haversine(lat, lng, p["lat"], p["lng"])) if lat is not None and lng is not None else None
    name = None
    file = request.files.get("photo")
    if file and file.filename and ext_of(file.filename) in IMG_EXT:
        try:
            img = Image.open(io.BytesIO(file.read()))
            img.load()
            plat, plng, _t = read_exif(img)
            if plat is not None:
                lat, lng = plat, plng
                dist = round(haversine(lat, lng, p["lat"], p["lng"]))
            name = save_image(img, CIT_DIR, 1400)
        except Exception:
            name = None
    db.execute("INSERT INTO signalements (project_id, name, phone, text, filename, lat, lng, distance, ip, created_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?)",
               (project_id, request.form.get("name", "").strip()[:80] or None,
                request.form.get("phone", "").strip()[:30] or None, text[:2000], name, lat, lng, dist, ip, now_iso()))
    log(project_id, L('Signalement citoyen reçu'), db, p["owner_id"])
    notify(project_id, owners_of(p), L('Signalement citoyen'), text[:300],
           url_for("project", project_id=project_id, onglet="dossier"), important=True)
    db.commit()
    flash(_("Merci. Votre signalement a été transmis au maître d'ouvrage."), "ok")
    return redirect(url_for("portal_project", project_id=project_id))


@app.route("/signalements/<int:sid>/photo")
def signalement_photo(sid):
    sg = get_db().execute("SELECT * FROM signalements WHERE id = ?", (sid,)).fetchone()
    if sg is None or not sg["filename"]:
        abort(404)
    if sg["hidden"] and not can("moderation"):
        abort(404)
    p = get_db().execute("SELECT * FROM projects WHERE id = ?", (sg["project_id"],)).fetchone()
    if not (p["kind"] == "public" and p["is_public"]):
        if not current_user():
            abort(404)
        load_project(p["id"])
    return send_from_directory(CIT_DIR, sg["filename"])


@app.route("/signalements/<int:sid>/reponse", methods=["POST"])
@login_required
def answer_signalement(sid):
    sg = get_db().execute("SELECT * FROM signalements WHERE id = ?", (sid,)).fetchone()
    if sg is None:
        abort(404)
    load_project(sg["project_id"], roles=("owner",))
    db = get_db()
    status = request.form.get("status") if request.form.get("status") in ("en_cours", "traite") else "traite"
    response = request.form.get("response", "").strip()[:1000] or None
    if status == "traite" and not response:
        flash(_("Écrivez la réponse publiée sur le portail."), "error")
        return redirect(url_for("project", project_id=sg["project_id"], onglet="dossier", _anchor="signalements"))
    db.execute("UPDATE signalements SET status = ?, response = COALESCE(?, response), answered_at = ? WHERE id = ?",
               (status, response, now_iso(), sid))
    log(sg["project_id"], L('Signalement citoyen traité') if status == "traite" else L("Signalement citoyen pris en charge"))
    db.commit()
    return redirect(url_for("project", project_id=sg["project_id"], onglet="dossier", _anchor="signalements"))


# --------------------------------------------------------------------------
# API de l'application mobile (Android, iPhone) - /api/v1
# --------------------------------------------------------------------------
def check_attestation(token, nonce, platform, user):
    """Statut d'attestation de l'appareil pour une preuve envoyee par l'application native."""
    db = get_db()
    if nonce:
        row = db.execute("SELECT * FROM attestation_nonces WHERE nonce = ? AND user_id = ?", (nonce, user["id"])).fetchone()
        db.execute("DELETE FROM attestation_nonces WHERE nonce = ?", (nonce,))
        if row is None or datetime.fromisoformat(row["created_at"]) < datetime.now(timezone.utc) - timedelta(minutes=30):
            return "refusee" if token else "absente"
    return ATTEST.verify(platform, token, nonce)


def api_error(message, code=400, **extra):
    return jsonify(ok=False, error=I18N.render(message), **extra), code


def api_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user() or not getattr(g, "api_token_id", None):
            return api_error(L("Connexion requise."), 401)
        return view(*args, **kwargs)
    return wrapped


def api_flash_result(resp):
    """Transforme le resultat d'une page (messages + redirection) en reponse JSON."""
    msgs = get_flashed_messages(with_categories=True)
    session.pop("_flashes", None)
    ok = not any(c == "error" for c, _m in msgs)
    return jsonify(ok=ok, messages=[m for _c, m in msgs]), (200 if ok else 400)


def user_json(u):
    return {k: u[k] for k in ("id", "name", "email", "phone", "role", "lang", "notify_whatsapp", "notify_sms",
                              "notify_email", "totp_on", "is_admin")}


def media_url(proof, thumb=False):
    if thumb:
        return url_for("proof_thumb", proof_id=proof["id"]) if proof["thumb"] else None
    return url_for("proof_photo", proof_id=proof["id"])


@app.route("/api/v1/connexion", methods=["POST"])
def api_login():
    f = request.get_json(silent=True) or request.form
    email = str(f.get("email", "")).strip().lower()
    if too_many_attempts(email):
        return api_error(L("Trop d'essais. Réessayez dans 15 minutes ou réinitialisez votre mot de passe."), 429)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ? AND deleted = 0", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], str(f.get("password", ""))):
        record_failure(email)
        return api_error(L("E-mail ou mot de passe incorrect."), 401)
    if user["blocked"]:
        return api_error(L("Ce compte est suspendu. Contactez le support."), 403)
    if user["totp_on"]:
        code = str(f.get("code") or "")
        if not code:
            return jsonify(ok=False, need_2fa=True), 200
        ok = SEC.totp_ok(user["totp_secret"], code)
        if not ok:
            codes = json.loads(user["backup_codes"] or "[]")
            if SEC.hash_code(code) in codes:
                codes.remove(SEC.hash_code(code))
                db.execute("UPDATE users SET backup_codes = ? WHERE id = ?", (json.dumps(codes), user["id"]))
                ok = True
        if not ok:
            record_failure(f"2fa:{user['id']}")
            return api_error(L("Code incorrect."), 401, need_2fa=True)
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO api_tokens (user_id, token_hash, device, session_version, created_at) VALUES (?,?,?,?,?)",
               (user["id"], hashlib.sha256(token.encode()).hexdigest(), str(f.get("device", ""))[:120],
                user["session_version"], now_iso()))
    lang = f.get("lang")
    if lang in I18N.LANGS and not user["lang"]:
        db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user["id"]))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return jsonify(ok=True, token=token, user=user_json(user))


@app.route("/api/v1/deconnexion", methods=["POST"])
@api_auth
def api_logout():
    db = get_db()
    db.execute("UPDATE api_tokens SET revoked = 1 WHERE id = ?", (g.api_token_id,))
    f = request.get_json(silent=True) or {}
    if f.get("push_token"):
        db.execute("DELETE FROM devices WHERE push_token = ?", (f["push_token"],))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/v1/compte/supprimer", methods=["POST"])
@api_auth
def api_delete_account():
    """Suppression du compte depuis l'application (exigée par l'App Store). Mot de passe demandé."""
    me = current_user()
    db = get_db()
    f = request.get_json(silent=True) or {}
    if too_many_attempts(f"del:{me['id']}"):
        return api_error(L("Trop d'essais. Réessayez dans 15 minutes ou réinitialisez votre mot de passe."), 429)
    if not check_password_hash(me["password_hash"], str(f.get("password", ""))):
        record_failure(f"del:{me['id']}")
        return api_error(L("Mot de passe incorrect."), 401)
    reason = account_deletion_blocker(db, me)
    if reason:
        return api_error(reason, 409)
    anonymize_account(db, me)
    return jsonify(ok=True, message=I18N.render(L("Votre compte a été supprimé et vos données personnelles effacées.")))


@app.route("/api/v1/moi", methods=["GET", "PUT"])
@api_auth
def api_me():
    me = current_user()
    if request.method == "PUT":
        f = request.get_json(silent=True) or {}
        db = get_db()
        if f.get("lang") in I18N.LANGS:
            db.execute("UPDATE users SET lang = ? WHERE id = ?", (f["lang"], me["id"]))
        if "phone" in f:
            db.execute("UPDATE users SET phone = ? WHERE id = ?", (str(f["phone"]).strip()[:30], me["id"]))
        for ch in ("whatsapp", "sms", "email"):
            if f"notify_{ch}" in f:
                db.execute(f"UPDATE users SET notify_{ch} = ? WHERE id = ?", (1 if f[f"notify_{ch}"] else 0, me["id"]))
        db.commit()
        me = db.execute("SELECT * FROM users WHERE id = ?", (me["id"],)).fetchone()
    out = user_json(me)
    out["paiements_a_confirmer"] = get_db().execute("SELECT COUNT(*) FROM payment_records WHERE payee_id = ? AND status = 'declare'",
                                                    (me["id"],)).fetchone()[0]
    return jsonify(ok=True, user=out)


@app.route("/api/v1/appareils", methods=["POST"])
@api_auth
def api_register_device():
    f = request.get_json(silent=True) or {}
    tok = str(f.get("push_token", "")).strip()
    if not tok.startswith(("ExponentPushToken[", "ExpoPushToken[")):
        return api_error(L("Jeton de notification invalide."))
    db = get_db()
    db.execute("DELETE FROM devices WHERE push_token = ?", (tok,))
    db.execute("INSERT INTO devices (user_id, push_token, platform, created_at) VALUES (?,?,?,?)",
               (current_user()["id"], tok, str(f.get("platform", ""))[:20], now_iso()))
    db.commit()
    return jsonify(ok=True)


def project_json(p, s, role, pred=None, full=False):
    out = {
        "id": p["id"], "name": p["name"], "address": p["address"], "lat": p["lat"], "lng": p["lng"],
        "radius": p["radius"], "role": role, "kind": p["kind"], "verified_pct": s["verified_pct"],
        "declared_pct": s["declared_pct"], "total": s["total"], "paid": s["paid"], "locked": s["locked"],
        "sequestre": s["sequestre"], "pay_mode": p["pay_mode"], "awaiting_pay": s["awaiting_pay"],
        "to_validate": s["to_validate"],
        "require_app_capture": bool(p["require_app_capture"]),
        "current": None, "prediction": None,
    }
    if s["current"]:
        c = s["current"]
        out["current"] = {"id": c["id"], "name": c["name"], "amount": c["amount"], "status": c["status"],
                          "status_label": _(STATUS_LABELS[c["status"]])}
    if pred:
        out["prediction"] = {"planned_end": pred["planned_end"].isoformat(), "predicted_end": pred["predicted_end"].isoformat(),
                             "delay": pred["delay"], "risk": pred["risk"], "risk_label": _(pred["risk"]),
                             "reasons": pred["reasons"], "done": pred["done"]}
    if full:
        out["steps"] = [{"id": st["id"], "position": st["position"], "name": st["name"], "amount": st["amount"],
                         "status": st["status"], "status_label": _(STATUS_LABELS[st["status"]]),
                         "pay_ref": st["pay_ref"], "declared_at": st["declared_at"], "paid_at": st["paid_at"]}
                        for st in s["steps"]]
    return out


@app.route("/api/v1/chantiers")
@api_auth
def api_projects():
    out, paid, total, to_validate = [], 0, 0, 0
    db = get_db()
    for p in user_projects(current_user()):
        s = project_stats(p["id"])
        j = project_json(p, s, project_role(p), project_prediction(p, s))
        cov = db.execute("SELECT id, created_at FROM proofs WHERE project_id = ? AND ok = 1 AND "
                         "(kind IS NULL OR kind != 'video' OR thumb IS NOT NULL) ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
        j["cover_url"] = url_for("proof_thumb", proof_id=cov["id"]) if cov else None
        j["cover_ago"] = ago(cov["created_at"]) if cov else None
        j["to_validate"] = s["to_validate"]
        out.append(j)
        paid, total, to_validate = paid + s["paid"], total + s["total"], to_validate + s["to_validate"]
    return jsonify(ok=True, projects=out, summary={"paid": paid, "total": total, "to_validate": to_validate,
                                                   "paid_short": compact(paid), "total_short": compact(total)})


@app.route("/api/v1/chantiers/<int:project_id>")
@api_auth
def api_project(project_id):
    p = load_project(project_id, roles=("owner", "chef", "inspecteur", "intervenant"))
    role = g.project_role
    db = get_db()
    s = project_stats(project_id)
    pred = project_prediction(p, s)
    out = project_json(p, s, role, pred, full=True)
    out["proofs"] = [{
        "id": pr["id"], "ok": bool(pr["ok"]), "kind": pr["kind"], "step_id": pr["step_id"], "step_name": pr["step_name"],
        "note": pr["note"], "created_at": pr["created_at"], "author": pr["author"], "distance": pr["distance"],
        "reasons": I18N.render_list(pr["reasons"]), "capture": pr["capture"], "attestation": pr["attestation"],
        "delayed_minutes": pr["delayed_minutes"], "url": media_url(pr), "thumb_url": media_url(pr, True),
        "ai_step": pr["ai_step"], "ai_same_site": pr["ai_same_site"], "ai_note": pr["ai_note"],
    } for pr in proofs_of(project_id)[:60]]
    if role == "owner":
        out["alerts"] = [{"title": a, "tab": t, "detail": d} for a, t, d in project_alerts(p, s, pred)]
        out["invite_code"] = p["invite_code"] if not p["chef_id"] else None
        out["escrow"] = s["escrow"]
    if role in ("owner", "chef"):
        out["orders"] = [order_json(db, o) for o in project_orders(db, project_id)]
    seed_checks(db, project_id)
    out["checks"] = [{"id": c["id"], "step_id": c["step_id"], "name": I18N.render(c["name"]), "required": bool(c["required"]),
                      "kind": c["kind"], "status": c["status"], "status_label": _(CHECK_STATUS[c["status"]]),
                      "value": c["value"], "unit": c["unit"], "note": c["note"]}
                     for c in db.execute("SELECT * FROM step_checks WHERE project_id = ? ORDER BY step_id, id", (project_id,))]
    if role == "owner":
        t = project_trust(p, db=db)
        out["trust"] = {"score": t["score"], "level": t["level"], "label": I18N.render(t["level_label"]),
                        "criteria": [{"key": c["key"], "title": I18N.render(c["title"]), "score": c["score"],
                                      "why": I18N.render(c["why"]), "tip": I18N.render(c["tip"]) if c["tip"] else None}
                                     for c in t["criteria"]]}
    if role in ("chef", "inspecteur"):
        out["capture_token"] = new_capture_token(db, project_id)
        out["inspections"] = [{"id": i["id"], "status": i["status"], "step_id": i["step_id"]}
                              for i in db.execute("SELECT * FROM inspections WHERE project_id = ? AND inspector_id = ?",
                                                  (project_id, current_user()["id"]))] if role == "inspecteur" else []
    return jsonify(ok=True, project=out)


@app.route("/api/v1/attestation/defi", methods=["POST"])
@api_auth
def api_attestation_nonce():
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode().rstrip("=")
    db = get_db()
    db.execute("INSERT INTO attestation_nonces (nonce, user_id, created_at) VALUES (?,?,?)",
               (nonce, current_user()["id"], now_iso()))
    db.execute("DELETE FROM attestation_nonces WHERE created_at < ?",
               ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),))
    db.commit()
    return jsonify(ok=True, nonce=nonce)


@app.route("/api/v1/chantiers/<int:project_id>/preuves", methods=["POST"])
@api_auth
def api_upload_proof(project_id):
    p = load_project(project_id, roles=("chef", "inspecteur"))
    user = current_user()
    if g.project_role == "inspecteur":
        iid = to_int(request.form.get("inspection_id"))
        i = get_db().execute("SELECT * FROM inspections WHERE id = ? AND inspector_id = ? AND status = 'acceptee'",
                             (iid, user["id"])).fetchone()
        if i is None:
            return api_error(L("Aucune inspection acceptée sur ce chantier."), 403)
        st = get_db().execute("SELECT * FROM steps WHERE id = ?", (i["step_id"],)).fetchone() if i["step_id"] else None
        st = st or project_stats(project_id)["current"]
        ok, reasons = process_proof(p, st, user, source="inspecteur", inspection_id=iid)
    else:
        st = project_stats(project_id)["current"]
        if st is None or st["status"] != "en_cours":
            return api_error(L("Aucune étape en cours n'accepte de preuve."), 409)
        ok, reasons = process_proof(p, st, user)
    if ok is None:
        return api_error(reasons)
    return jsonify(ok=bool(ok), proof_id=g.last_proof_id, reasons=[I18N.render(r) for r in reasons],
                   a_verifier=bool(g.get("last_proof_suspect")),
                   message=_("Preuve vérifiée et envoyée au propriétaire.") if ok else _("Preuve envoyée mais refusée : ")
                   + "; ".join(I18N.render(r) for r in reasons)), 201


def json_as_form():
    """Le corps JSON de l'application alimente les memes champs que les formulaires web."""
    f = request.get_json(silent=True)
    if f:
        request.form = type(request.form)({k: str(v) for k, v in f.items() if v is not None})


@app.route("/api/v1/rejoindre", methods=["POST"])
@api_auth
def api_join():
    json_as_form()
    return api_flash_result(join_project())


@app.route("/api/v1/chantiers/<int:project_id>/etapes/<int:step_id>/<action>", methods=["POST"])
@api_auth
def api_step_action(project_id, step_id, action):
    views = {"declarer": declare_step, "valider": validate_step, "refuser": refuse_step}
    if action not in views:
        abort(404)
    json_as_form()
    return api_flash_result(views[action](project_id=project_id, step_id=step_id))


def order_json(db, o):
    return {"id": o["id"], "ref": o["ref"], "status": o["status"], "status_label": _(ORDER_STATUS[o["status"]]),
            "project_id": o["project_id"], "project_name": o["project_name"], "address": o["address"],
            "supplier": o["supplier_name"], "step_name": o["step_name"], "total": o["total"],
            "received_total": o["received_total"], "pay_mode": o["pay_mode"], "delivery_date": o["delivery_date"],
            "note": o["note"], "problem": o["problem"], "created_at": o["created_at"],
            "lines": [{"id": ln["id"], "name": ln["name"], "material": ln["material"], "unit": ln["unit"], "qty": ln["qty"],
                       "unit_price": ln["unit_price"], "qty_received": ln["qty_received"]} for ln in order_lines(o["id"], db)]}


@app.route("/api/v1/commandes")
@api_auth
def api_orders():
    """Commandes du fournisseur connecte (les chantiers voient les leurs dans /api/v1/chantiers/<id>)."""
    me = current_user()
    if me["role"] != "fournisseur":
        return api_error(L("Réservé aux fournisseurs."), 403)
    db = get_db()
    out = []
    for o in project_orders(db, supplier_id=me["id"]):
        j = order_json(db, o)
        if o["status"] in ("acceptee", "livree"):
            j["capture_token"] = new_capture_token(db, o["project_id"])
            p = db.execute("SELECT lat, lng, radius FROM projects WHERE id = ?", (o["project_id"],)).fetchone()
            j["site"] = {"lat": p["lat"], "lng": p["lng"], "radius": p["radius"]}
        out.append(j)
    db.commit()
    return jsonify(ok=True, orders=out)


@app.route("/api/v1/commandes/<int:oid>/<action>", methods=["POST"])
@api_auth
def api_order_action(oid, action):
    """approuver, annuler, accepter, refuser, receptionner, probleme, payee ; livraison (photo multipart)."""
    if action == "livraison":
        return api_flash_result(order_delivery(oid=oid))
    actions = {"approuver": "approve", "annuler": "cancel", "accepter": "accept", "refuser": "refuse",
               "receptionner": "receive", "probleme": "problem", "payee": "paid"}
    if action not in actions:
        abort(404)
    json_as_form()
    form = request.form.copy()
    form["action"] = actions[action]
    request.form = form
    return api_flash_result(order(oid=oid))


@app.route("/api/v1/notifications", methods=["GET", "POST"])
@api_auth
def api_notifications():
    me = current_user()
    db = get_db()
    if request.method == "POST":
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (me["id"],))
        db.commit()
        return jsonify(ok=True)
    rows = db.execute("SELECT * FROM notifications WHERE user_id = ? AND channel = 'app' ORDER BY id DESC LIMIT 100",
                      (me["id"],)).fetchall()
    return jsonify(ok=True, unread=sum(1 for r in rows if not r["is_read"]), notifications=[
        {"id": r["id"], "project_id": r["project_id"], "title": I18N.render(r["title"]), "body": I18N.render(r["body"]),
         "link": r["link"], "read": bool(r["is_read"]), "created_at": r["created_at"]} for r in rows])


# --- Paiements suivis dans l'application mobile ---
def pay_record_json(db, r, due=None):
    due = due or payment_due(db, r["kind"], r["ref_id"])
    return {"id": r["id"], "bon_a_payer": due["ref"] if due else None, "objet": r["kind"], "objet_id": r["ref_id"],
            "libelle": I18N.render(due["label"]) if due else "", "chantier": due["project"]["name"] if due else "",
            "chantier_id": r["project_id"], "montant": r["amount"], "moyen": r["method"],
            "moyen_label": _(PAY_METHODS[r["method"]]), "reference": r["reference"], "date": r["paid_on"],
            "statut": r["status"], "statut_label": _(PAY_REC_STATUS[r["status"]]), "recu": bool(r["receipt"]),
            "payeur": user_name(db, r["payer_id"]), "motif": r["contest_note"]}


def due_json(db, d):
    payee = db.execute("SELECT name, phone, company FROM users WHERE id = ?", (d["payee_id"],)).fetchone() if d["payee_id"] else None
    return {"objet": d["kind"], "objet_id": d["ref_id"], "bon_a_payer": d["ref"], "libelle": I18N.render(d["label"]),
            "chantier": d["project"]["name"], "chantier_id": d["project"]["id"], "montant_du": d["amount"],
            "confirme": d["confirmed"], "declare": d["declared"], "reste": d["remaining"], "ouvert": d["open"],
            "paye": d["done"], "beneficiaire": (payee["company"] or payee["name"]) if payee else None,
            "telephone": payee["phone"] if payee else None, "code": d["code"],
            "paiements": [pay_record_json(db, r, d) for r in d["records"]]}


@app.route("/api/v1/paiements")
@api_auth
def api_payments():
    """A confirmer (je suis beneficiaire), a payer (je suis payeur), et historique."""
    me = current_user()
    db = get_db()
    received = db.execute("SELECT * FROM payment_records WHERE payee_id = ? ORDER BY status = 'declare' DESC, id DESC LIMIT 100",
                          (me["id"],)).fetchall()
    to_pay = []
    for p in user_projects(me):
        if me["id"] not in (finance_members(db, p) or owners_of(p, db)):
            continue
        for d in project_payments(db, p):
            if d["open"] and d["remaining"] > 0:
                to_pay.append(due_json(db, d))
    return jsonify(ok=True, a_confirmer=[pay_record_json(db, r) for r in received if r["status"] == "declare"],
                   recus=[pay_record_json(db, r) for r in received if r["status"] != "declare"], a_payer=to_pay,
                   moyens=tr(PAY_METHODS))


@app.route("/api/v1/paiements/<kind>/<int:ref_id>", methods=["GET", "POST"])
@api_auth
def api_pay_order(kind, ref_id):
    db = get_db()
    d = payment_due(db, kind, ref_id)
    if d is None:
        return api_error(L("Introuvable."), 404)
    if not pay_access(d, current_user()):
        return api_error(L("Accès refusé."), 403)
    if request.method == "GET":
        return jsonify(ok=True, bon=due_json(db, d))
    if not request.files:
        json_as_form()
    return api_flash_result(pay_order(kind=kind, ref_id=ref_id))


@app.route("/api/v1/paiements/recus/<int:rid>", methods=["POST"])
@api_auth
def api_payment_answer(rid):
    json_as_form()
    return api_flash_result(payment_answer(rid=rid))


@app.route("/api/v1/version")
def api_version():
    return jsonify(ok=True, api=1, min_app_version=env("MIN_APP_VERSION", "1.0.0"))


# --------------------------------------------------------------------------
# Application installable (PWA)
# --------------------------------------------------------------------------
def make_icons():
    folder = os.path.join(BASE_DIR, "static", "icons")
    os.makedirs(folder, exist_ok=True)
    for size in (192, 512):
        path = os.path.join(folder, f"icon-{size}.png")
        if os.path.exists(path):
            continue
        from PIL import ImageDraw
        im = Image.new("RGB", (size, size), (14, 90, 58))
        dr = ImageDraw.Draw(im)
        u = size / 16
        dr.polygon([(3 * u, 8 * u), (8 * u, 3.5 * u), (13 * u, 8 * u)], fill=(255, 255, 255))
        dr.rectangle([4.5 * u, 8 * u, 11.5 * u, 13 * u], fill=(255, 255, 255))
        dr.line([(6 * u, 10.5 * u), (7.5 * u, 12 * u), (10.5 * u, 9 * u)], fill=(180, 80, 31), width=int(u * 0.9))
        im.save(path)


@app.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "ChantierVrai", "short_name": "ChantierVrai", "lang": "fr", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#F5F3EE", "theme_color": "#0E5A3A",
        "description": "Suivi de chantier à distance avec preuves vérifiées",
        "icons": [{"src": url_for("static", filename=f"icons/icon-{s}.png"), "sizes": f"{s}x{s}", "type": "image/png",
                   "purpose": "any maskable"} for s in (192, 512)],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/hors-ligne")
def offline():
    return render_template("offline.html")


# --------------------------------------------------------------------------
# Erreurs
# --------------------------------------------------------------------------
@app.errorhandler(413)
def too_large(_e):
    flash(_('Fichier trop lourd (120 Mo maximum).'), "error")
    return redirect(request.referrer or url_for("home"))


init_db()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
