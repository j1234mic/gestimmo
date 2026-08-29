# Compléments et modules manquants — GestImmo

Analyse réalisée le 2026-08-29 sur la branche `arena/01a04c7d-gestimmo`.

**Mise à jour du 2026-08-29** : les manques identifiés sur les modules
existants ont été implémentés (modules 1, 2 et 15 : vidéos, visite 360°,
filtres, recherches favorites, exports, rapport d'évaluation, historique
consolidé, signature de mandat avec preuve, synthèse financière par bien,
cycle de vie des sinistres et attestations). Les sections 18 à 31 ci-dessous
sont désormais **implémentées côté backend** sous `/api/extension` (et
`/api/public-portal` pour le Module 22) et couvertes par
`backend/tests/test_extension_modules.py`. La suite passe de 64 à
**95 tests d'intégration verts**. Peuvent être considérés comme des
**extensions métier optionnelles ou à affiner** : la totale des points 3.2
(mais les endpoints sont journalisés) et 3.4 (i18n, multi-devise, white-label,
observabilité).

---

## 0. Constat de départ

Les 17 modules actuels couvrent **le cœur** d'un logiciel de gestion
immobilière (biens, propriétaires, locataires, baux, finance, maintenance,
copropriété, CRM, reporting, notifications, GED, admin/sécurité, carto,
mobile, assurances, IA, intégrations).

Mais deux choses sont vraies en même temps :

1. **Les 17 modules ne sont pas tous « complets » dans le repo.**
   D'après `AUDIT-MODULES.md` :
   - Modules **1 (biens) et 2 (propriétaires)** : inachevés et **sans aucun test**
     (vidéos de galerie, visite 360°, recherches favorites, filtres par
     propriétaire/gestionnaire, export CSV, rapport d'évaluation PDF,
     signature de mandat réelle, synthèse financière par bien).
   - Module **14 (mobile)** : socle API seulement, **aucune app** noumérique.
   - Module **15 (assurances)** : cycle de vie du sinistre et suivi des
     attestations manquants.
   - Le dépôt est **API-FastAPI uniquement** : aucun frontend web, aucun
     projet mobile, aucun écran de portail.

2. **Même quand le module est complet, il manque des domaines fonctionnels
   entiers** qui ne sont pas dans le cahier des charges initial.

Ce document liste ces compléments, du plus stratégique au plus optionnel.

---

## 1. Modules indispensables / fortement recommandés (nouveaux blocs)

### Module 18 — Location courte durée & saisonnière (Airbnb / Booking / Abritel)

Le Module 4 couvre le **bail saisonnier** juridique, mais pas la gestion
opérationnelle d'une plateforme de location courte durée.

**Ce qui manque :**
- Calendrier d'occupation multi-canal (Bnb, Airbnb, Booking, Abritel, direct).
- Réservation / blocage / annulation avec synchronisation externe.
- Check-in / check-out, consignes, inventaire, ménage, linge.
- Tarification dynamique (saison, week-end, taux d'occupation, comparables).
- Paiement, séquestre, dépôt de garantie, acompte et détection de fraude.
- Gestion des taxes de séjour / taxes locales / redevances.
- Reporting par bien : TRevPAR, RevPAR, taux d'occupation, noctées.

### Module 19 — Contentieux & conformité juridique avancée

Le Module 5 amorce le contentieux (impayés, huissier, tribunal). Il manque un
**pilotage juridique complet**.

- Dossier contentieux multi-corps : impayé, troubles de jouissance, bail,
  copropriété, litige prestataire.
- Suivi des actes : assignation, injonction de payer, commandement, signification.
- Échéancier procédural, dates d'audience, greffe, conseil.
- Modèles de courriers recommandés / AR (plusieurs). 
- Suivi des frais de procédure, provisions, recouvrement.
- Médiation / conciliation / procédure participative.
- Conformité reglementaire : lutte anti-blanchiment (LCB-FT), KYC propriétaires,
  vérification des personnes politiquement exposées, gel des avoirs.

### Module 20 — Fiscalité & déclarations immobilières

L'actuel « aide à la déclaration » propriétaire est un point de départ, mais
pas un module fiscal.

- Régime réel vs micro-foncier, calcul du résultat fiscal.
- Déclarations 2044, 2072-S, TVA immobilier, IFI.
- Plus-value immobilière sur vente (abattements, exonérations).
- Taxe foncière, taxe d'habitation, taxe de séjour, prélèvement à la source.
- Loyer + charges récupérables, amortissements, travaux déductibles.
- Génération des tableaux fiscaux par propriétaire / SCI.
- Export fiscal au format DGFiP / tableur / PDF.

### Module 21 — Financement & gestion des prêts

Même pour une agence, le propriétaire investisseur veut suivre son
financement.

- Tableau d'amortissement (différé, linéaire, variable, relais).
- Critères de financement : taux, durée, assurance, frais, PTZ.
- Gestion des prêts en cours, amortissements, intérêts, échéanciers.
- Refinancement / renégociation / anticipation.
- Covenants, banques, garanties, gestion des nantissements.

### Module 22 — Portail public / site vitrine de l'agence

Le repo n'a **aucun frontend**. Pour un outil réellement utilisable, il faut
au minimum un portail public.

- Site vitrine agence (annonces, ville, recherche, SEO).
- Fiche bien publique avec galerie, plan, contact, prise de rendez-vous.
- Candidature en ligne, estimation gratuite, demande de visite.
- Suivi de demande (jeton / email), sans login obligatoire.
- CMS pages, actualités, agents, avis clients, cookies RGPD.
- Carte des biens publiques, formulaire de contact, WhatsApp / appel.

### Module 23 — Gestion des services résidentiels & conciergerie

Modèle fréquent en location meublée, résidence étudiante / senior, coliving.

- Contrats de services (ménage, linge, parking, Wifi, énergie, home services).
- Facturation récurrente des services + consommations réelles.
- Colocation / multi-occupants : répartition des charges, dépôts, plafonds.
- Résidences gérées : taux d'occupation par unité, revenue par lit.
- Conciergerie : réception, colis, clés, interventions, incidents.

### Module 24 — Accès, clés & sûreté

Très utile opérationnellement et absent.

- Registre des clés / badge / code / digicode par bien et par bail.
- Remise / retour encadrés (locataire, propriétaire, prestataire, agence).
- Alerte non-restitution ou retard.
- Historique des accès, dépôt au coffre, changement de serrure.
- Gestion des accès aux parties communes (si syndic intégré).

### Module 25 — Compteurs & consommation énergie

Le Module 4 saisit les compteurs à l'état des lieux. Il manque le **suivi
dans le temps**.

- Relevés mensuels / annuels électricité, gaz, eau, chauffage.
- Photo / OCR / import de relevés, correction de facture.
- Facturation des consommations aux locataires.
- Comparaison de consommation, détection d'anomalies / fuites.
- Rapports énergie par bien, années, saisons.

---

## 2. Modules utiles selon l'orientation produit (optionnels)

### Module 26 — Développement & promotion immobilière (VEFA)

Si l'outil doit dépasser la gestion pour couvrir la promotion / l'aménagement.

- Opérations immobilières : programme, lots, VEFA, permis de construire.
- Suivi de chantier, jalons, avancement, réception, garanties.
- Commercialisation en VEFA, contrats de réservation, états descriptifs.
- Gestion des surfaces, plans, diagnostics, livraison.

### Module 27 — Investisseurs & gestion de fonds / SCPI

Si le produit vise l'investissement institutionnel ou collectif.

- SCPI, SCI, crowdfunding, club deals, parts sociales.
- Souscription, parts, distributions, reportings investisseurs.
- Suivi de NAV, rendement, TRI, value at risk.
- Gestion des investisseurs / LP, KYC, correspondances.

### Module 28 — Performance énergétique & rénovation

Très porteur réglementairement (DPE, décret tertiaire, aides).

- Audit énergétique, plans de rénovation.
- Suivi des aides (MaPrimeRénov', CEE, aides locales).
- Label / notation énergie, recommandation de travaux avec ROI.
- Objectifs de consommation, reporting de performance.

### Module 29 — Qualité de service & satisfaction clients

Un bon logiciel de gestion doit mesurer la satisfaction.

- Enquêtes de satisfaction locataire / propriétaire (NPS, CSAT).
- Avis sur prestataires, gestionnaires, agence.
- Alertes en cas de note faible / churn risque.
- Historique des retours, plans d'amélioration.

### Module 30 — Tâches, plannings & workflow interne

Les notifications et tickets existent, mais pas un **gestionnaire de tâches**
interne transversal.

- Tâches assignables (individu, équipe, rôle).
- Priorité, échéance, relance, dépendances.
- Vue Kanban / agenda / liste.
- Intégration avec tickets, mandats, baux, prospects.
- SLA interne, suivi de performance des équipes.

### Module 31 — Sourcing & acquisitions immobilières

Utile pour agences / investisseurs.

- Prospection de biens, foncier, petits annonces, sourcing.
- Analyse rapide : prix / m², rentabilité, travaux, comparables.
- Due diligence, check-lists, espace documentaire.
- Portefeuille d'opportunités et scoring.

---

## 3. Améliorations transverses à ne pas oublier

Au-delà de modules, il manque beaucoup de **traverses** qui rendent un outil
réellement exploitable :

### 3.1 Frontend / expérience

- Aucun frontend : site vitrine, back-office, portails.
- Widgets drag & drop du dashboard (Module 9) non rendus.
- Vues liste / grille / carte non rendues.
- Application mobile / PWA non construite.
- Mode hors-ligne non réel (la sync n'est pas rejouée sur les entités métier).

### 3.2 Intégrations réelles (les endpoints sont journalisés, pas branchés)

- Envoi email / SMS / courrier réel (SMTP, Mailgun, SendGrid, Twilio, OVH).
- Signature électronique réellement appelée (DocuSign, Yousign, HelloSign).
- Paiement réel Stripe GoCardless (déjà amorcé Stripe webhooks).
- Banque réellement synchronisée (import OFX/CSV/MT940 seulement).
- Portails immobiliers réellement diffusés (SeLoger, LeBonCoin, etc.).
- Géocodage réel, cartes, itinéraires (l'actuel est une estimation Haversine).
- CRM externe (HubSpot, Salesforce) réellement synchronisé.
- BI (Power BI, Tableau) par export JSON / API, pas de connecteur natif.

### 3.3 Écarts fonctionnels dans les modules existants

- **Module 1** : vidéos, visite 360°, recherches favorites, filtres
  propriétaire/gestionnaire/date/tags, exports CSV, rapport d'évaluation PDF,
  historique consolidé bien (locataires, loyers, travaux).
- **Module 2** : signature électronique du mandat = simple changement de
  statut, pas de dossier de preuve ; synthèse financière par bien absente.
- **Module 15** : pas de détail / mise à jour d'un sinistre, pas de suivi
  des attestations, CRUD contrats incomplet, pas de pagination ni cloisonnement.
- **Module 7** : convocations / PV, mais pas de notification réelle, pas de
  portail copropriétaire, pas de gestion des appels de fonds en défaut.
- **Module 8** : diffusion multi-portails et statistiques métriques seulement ;
  pas de publication réelle, pas de plan de contact automatisé.
- **Module 10** : les envois sont journalisés (statut "pending") mais pas
  réellement délivrés par un prestataire.
- **Module 16** : les modèles IA sont heuristiques / déterministes, pas de
  ré-entraînement ni d'ingestion de données de marché en continu.

### 3.4 Non-fonctionnels

- **i18n / multi-langue** (FR/EN/…).
- **Multi-devise** (les coûts deviennent cross-border).
- **Export PDF / Excel natif de tous les écrans**.
- **API documentation / versioning / sandbox** (swagger peut suffire, mais un
  portail développeur + clés / quotas / webhooks est utile).
- **SLA / surveillance / observabilité** (metrics, alertes techniques, health).
- **White-label** multi-entreprises (déjà multi-agences).
- **Authentification externe SAML/OAuth2 réellement configurable** (partiel).
- **Processus de maintenance** : sauvegardes, purge, archiving, migration.
- **Conformité** : RGPD (présent), mais aussi LCB-FT, DORA, LCEN, CPF selon
  le marché.

---

## 4. Roadmap suggérée par impact

### Sprint 1 — Fiabiliser l'existant (à faire en premier)

1. Terminer et **tester** les Modules 1 et 2.
2. Compléter le cycle de vie des **assurances** (Module 15).
3. Construire le **frontend back-office** et les **portails** propriétaire /
   locataire (au minimum PWA).
4. Rendre réel l'**envoi** (email / SMS) et la **signature** en production.

### Sprint 2 — Gains métier immédiats

5. **Portail public / site vitrine** (annonces + candidature + estimation).
6. **Contentieux** complet (impayé → recouvrement).
7. **Fiscalité** propriétaire / SCI.
8. **Clés / accès**.
9. **Tâches & workflow interne**.

### Sprint 3 — Différenciation

10. **Courte durée** (si stratégie agence locative).
11. **Financement / investisseurs** (si stratégie investisseur).
12. **Performance énergétique / rénovation**.
13. **Résidences gérées / conciergerie**.
14. **Développement / VEFA** (si étranger au cœur de métier, à valider).

---

## 5. Conclusion

Le repo a un **socle backend très solide** (67 routes, modèles, services,
tests) pour le cœur de la gestion locative classique. Pour en faire un
produit « gestion immobilière » complet, il manque :

- **le frontend** (obligatoire : sans écrans, l'API n'est pas utilisable),
- **la complétion des modules 1, 2, 14, 15** (déjà documentée dans
  `AUDIT-MODULES.md`),
- **les intégrations réelles** (email, SMS, signature, paiement, banque,
  portails) au lieu de simples journalisations,
- et **5 à 8 domaines fonctionnels** : courte durée, contentieux, fiscalité,
  financement, accès/clés, compteurs/énergie, portail public, qualité de
  service — selon l'orientation commerciale (location, vente, syndic,
  promotion, investissement).
