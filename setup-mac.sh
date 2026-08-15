#!/bin/bash
# ContaApp RH — Instalación en Mac (uso personal, desde código fuente)
set -e

echo "=== ContaApp RH setup para Mac ==="

# 1. Entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Dependencias (psycopg2-binary puede fallar en Apple Silicon — si falla, ver abajo)
pip install --upgrade pip
pip install Pillow SQLAlchemy reportlab || true

# Intentar psycopg2-binary; si falla, instalar psycopg2 (requiere: brew install postgresql)
pip install psycopg2-binary 2>/dev/null || pip install psycopg2

echo ""
echo "✓ Instalación completa."
echo ""
echo "Para arrancar ContaApp RH:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
