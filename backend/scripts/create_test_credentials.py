#!/usr/bin/env python3
"""Script pour créer des comptes de connexion pour propriétaires et locataires existants."""

import os
import sys
import sqlite3
import secrets
import string
import hashlib

# Chemin vers la base (dans backend/)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test.db')

def hash_password(password: str) -> str:
    """Simule le hash bcrypt pour les tests."""
    salt = secrets.token_hex(16)
    return f"$2b$12${salt}${hashlib.sha256((salt + password).encode()).hexdigest()[:53]}"

def create_owner_credentials(db_path: str):
    """Crée des comptes AdminUser pour les propriétaires existants."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("=" * 60)
    print("CRÉATION DES COMPTES PROPRIÉTAIRES")
    print("=" * 60)
    
    cur.execute("""
        SELECT id, reference, email, first_name, last_name, company_name 
        FROM owners 
        WHERE email IS NOT NULL AND email != '' 
        AND is_active = 1
    """)
    owners = cur.fetchall()
    
    print(f"\nPropriétaires trouvés: {len(owners)}")
    
    created = []
    existing = []
    
    for owner in owners:
        email = owner['email'].lower().strip()
        
        cur.execute("SELECT id, email, full_name, is_active FROM admin_users WHERE email = ?", (email,))
        existing_user = cur.fetchone()
        
        if existing_user:
            print(f"\n  [DÉJÀ EXISTANT] {owner['reference']}")
            print(f"    Email: {existing_user['email']}")
            existing.append(owner['reference'])
            continue
        
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        temp_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        password_hash = hash_password(temp_password)
        
        full_name = owner['company_name'] or f"{owner['first_name'] or ''} {owner['last_name'] or ''}".strip()
        if not full_name:
            full_name = email
        
        public_id = secrets.token_hex(16)
        cur.execute("""
            INSERT INTO admin_users 
            (public_id, email, full_name, phone, password_hash, is_active, 
             is_superuser, must_change_password, failed_login_attempts, locked_until,
             two_factor_enabled, two_factor_method, two_factor_secret, locale, timezone,
             last_login_at, deactivated_at, deactivated_reason)
            VALUES (?, ?, ?, ?, ?, 1, 0, 1, 0, NULL, 0, NULL, NULL, 'fr', 'Europe/Paris', NULL, NULL, NULL)
        """, (public_id, email, full_name, None, password_hash))
        
        user_id = cur.lastrowid
        
        cur.execute("SELECT id FROM admin_roles WHERE profile_key = 'viewer' AND is_system = 1")
        viewer_role = cur.fetchone()
        
        if viewer_role:
            cur.execute("""
                INSERT INTO admin_user_roles (user_id, role_id, organization_id, agency_id, assigned_by)
                VALUES (?, ?, NULL, NULL, 'seed_owner_credentials')
            """, (user_id, viewer_role['id']))
        
        conn.commit()
        
        print(f"\n  [CRÉÉ] {owner['reference']}")
        print(f"    Email: {email}")
        print(f"    Mot de passe: {temp_password}")
        print(f"    Portail: /owner-portal/dashboard")
        
        created.append({
            'reference': owner['reference'],
            'email': email,
            'password': temp_password,
            'full_name': full_name
        })
    
    conn.close()
    return created, existing

def create_tenant_portal_access(db_path: str):
    """Active le portail pour les locataires existants ou crée des locataires de test."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("\n" + "=" * 60)
    print("ACTIVATION DU PORTAL LOCATAIRE")
    print("=" * 60)
    
    cur.execute("""
        SELECT id, reference, email, first_name, last_name, portal_enabled
        FROM tenants 
        WHERE is_active = 1 AND email IS NOT NULL AND email != ''
    """)
    tenants = cur.fetchall()
    
    print(f"\nLocataires actifs trouvés: {len(tenants)}")
    
    if len(tenants) == 0:
        print("\n  Création de locataires de test...")
        
        test_tenants = [
            {
                'reference': 'TEST-TEN-001',
                'first_name': 'Marie',
                'last_name': 'Dubois',
                'email': 'marie.dubois@test.com',
                'phone': '0612345678',
                'city': 'Paris',
                'password': 'Tenant2024!'
            },
            {
                'reference': 'TEST-TEN-002',
                'first_name': 'Jean',
                'last_name': 'Martin',
                'email': 'jean.martin@test.com',
                'phone': '0698765432',
                'city': 'Lyon',
                'password': 'Tenant2024!'
            }
        ]
        
        for t in test_tenants:
            password_hash = hash_password(t['password'])
            
            cur.execute("""
                INSERT INTO tenants 
                (reference, status, first_name, last_name, email, phone, mobile, 
                 address, postal_code, city, country, employment_status, occupation,
                 employer_name, solvency_score, reliability_score, portal_password_hash,
                 portal_enabled, is_active, notes, tags, created_at, updated_at)
                VALUES (?, 'active', ?, ?, ?, ?, ?, NULL, NULL, ?, 'France', 'employee', 'engineer',
                        NULL, 85.0, 90.0, ?, 1, 1, NULL, NULL, datetime('now'), datetime('now'))
            """, (
                t['reference'], t['first_name'], t['last_name'], t['email'],
                t['phone'], t.get('mobile', ''), t['city'], password_hash
            ))
            print(f"\n  [CRÉÉ] {t['reference']}: {t['email']} / {t['password']}")
            
            print(f"\n  [CRÉÉ] {t['reference']}")
            print(f"    Email: {t['email']}")
            print(f"    Mot de passe: {t['password']}")
            print(f"    Portail: /tenant-portal/dashboard")
        
        conn.commit()
        
        # Relecture
        cur.execute("""
            SELECT id, reference, email, first_name, last_name, portal_enabled
            FROM tenants 
            WHERE reference LIKE 'TEST-TEN%'
        """)
        tenants = cur.fetchall()
    
    print("\n  Locataires avec accès portail:")
    for tenant in tenants:
        print(f"\n    {tenant['reference']}")
        print(f"      Email: {tenant['email']}")
        print(f"      Portail: {'Activé' if tenant['portal_enabled'] else 'Non activé'}")
    
    conn.close()
    return tenants

def main():
    db_path = DB_PATH
    
    if not os.path.exists(db_path):
        print(f"ERREUR: Base de données {db_path} non trouvée")
        sys.exit(1)
    
    print(f"\nBase de données: {db_path}")
    print(f"Taille: {os.path.getsize(db_path) / 1024:.1f} Ko\n")
    
    owners_created, owners_existing = create_owner_credentials(db_path)
    tenants = create_tenant_portal_access(db_path)
    
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    print(f"\nPropriétaires:")
    print(f"  - Créés: {len(owners_created)}")
    print(f"  - Déjà existants: {len(owners_existing)}")
    print(f"\nLocataires:")
    print(f"  - Total: {len(tenants)}")
    
    if owners_created:
        print(f"\n  📌 TEST PROPRIÉTAIRE:")
        print(f"     POST /api/auth/login")
        print(f"     Body: {{\"email\": \"EMAIL\", \"password\": \"PASSWORD\"}}")
        print(f"     → Récupérer access_token")
        print(f"     → GET /owner-portal/dashboard (Authorization: Bearer TOKEN)")
    
    if tenants:
        print(f"\n  📌 TEST LOCATAIRE:")
        print(f"     POST /tenant-portal/login")
        print(f"     Body: {{\"email\": \"EMAIL\", \"password\": \"PASSWORD\"}}")
        print(f"     → Récupérer access_token")
        print(f"     → GET /tenant-portal/dashboard (Authorization: Bearer TOKEN)")

if __name__ == '__main__':
    main()
