"""Architecture hexagonale (ports & adapters).

Ce package isole le domaine métier (``domain``) des adaptateurs techniques
(SQLAlchemy, FastAPI…). Il est organisé en quatre sous-couches :

- ``domain``      : entités métier pures et ports (interfaces)
- ``application`` : cas d'usage (use cases) et DTO applicatifs
- ``infrastructure`` : adaptateurs (SQLAlchemy, sécurité)
- ``web``         : adaptateur HTTP (routeurs FastAPI v2)

La logique métier d'origine n'est pas modifiée : les anciens modules
``app.services.*`` / ``app.routes.*`` continuent de fonctionner et sont
reliés à cette architecture via des adaptateurs de compatibilité.
"""
