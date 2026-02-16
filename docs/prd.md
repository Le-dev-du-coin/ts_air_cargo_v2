---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-03-success', 'step-e-01-discovery', 'step-e-02-review', 'step-e-03-edit']
inputDocuments: ['_bmad-output/planning-artifacts/product-brief-ts_air_cargo_v2-2026-02-06.md']
workflowType: 'prd'
workflow: 'edit'
classification:
  projectType: 'web_app'
  domain: 'logistics'
  complexity: 'medium'
  projectContext: 'greenfield'
lastEdited: '2026-02-09'
editHistory:
  - date: '2026-02-09'
    changes: 'Amélioration générale selon standards BMAD - Ajout 6 sections (Executive Summary, User Journeys, Domain Requirements, Project-Type Requirements, Functional Requirements, Non-Functional Requirements) + Amélioration 2 sections existantes (Success Criteria avec traçabilité, Product Scope standardisé français)'
---

# Product Requirements Document - ts_air_cargo_v2

**Author:** MaliandevBoy
**Date:** 2026-02-06

## Executive Summary

ts_air_cargo_v2 digitalise la gestion logistique des agences de transit Chine-Afrique de l'Ouest. La plateforme remplace la gestion manuelle Excel par une solution centralisée offrant traçabilité totale du dépôt en Chine à la livraison finale.

**Problème Résolu:** Gestion manuelle Excel déconnectée provoque visibilité limitée, groupages aériens complexes, gestion financière fastidieuse, surcharge service client.

**Solution Proposée:** Application web unifiée intégrant (1) gestion opérationnelle stocks/vols, (2) portail client self-service, (3) module financier factures/paiements.

**Différenciateurs Clés:**
- Visibilité bout-en-bout : réception Chine jusqu'à main client Bamako/Abidjan
- Centralisation : logistique et finance unifiées, zéro double saisie

**Utilisateurs Cibles:**
- Agent Chine : réception rapide (scan + photo webcam + pesée < 15s)
- Agent ML/RCI : distribution rigoureuse avec rapport journalier automatisé
- Client Importateur : autonomie via notifications WhatsApp et portail tracking
- Super Admin : supervision globale multi-pays



## Success Criteria

### User Success

*   **Agent Chine (Vitesse)** : Enregistrement d'un colis (Scan + Photo + Pesée) en **moins de 15 secondes**.
    - **Traçabilité:** Journey 1 - Agent Chine Réception
*   **Agent Mali/RCI (Sérénité)** : **Zéro écart de caisse** lors de la clôture journalière grâce au rapport automatisé.
    - **Traçabilité:** Journey 2 - Agent ML/RCI Clôture
*   **Client (Autonomie)** : Réduction de **50% des appels entrants** pour demander "Où est mon colis ?".
    - **Traçabilité:** Journey 3 - Client Tracking

### Business Success

*   **Scalabilité** : Capacité à traiter **2x plus de volume** sans recruter de personnel administratif supplémentaire.
*   **Protection des Revenus** : Élimination des colis perdus ou non-facturés grâce à la traçabilité de bout en bout (100% de concordance).
    - **Traçabilité:** Domain Requirements DR-01 (Traçabilité Bout-en-Bout)
*   **Flux de Trésorerie** : Accélération du cycle d'encaissement.

### Technical Success

*   **Wachap Reliability** : **100% de délivrabilité** des notifications (système Queue & Retry avec 0% de perte en cas de déconnexion).
    - **Traçabilité:** FR-024, FR-025, NFR-010 (Queue Notifications)
*   **Performance Reporting** : Génération du rapport PDF journalier en < 5 secondes.
    - **Traçabilité:** FR-021, NFR-003 (Génération PDF)

### Measurable Outcomes

1.  **Temps de traitement moyen** par colis (Réception).
2.  **Taux de colis livrés** vs colis reçus (Objectif 100%).
3.  **Nombre de tickets/appels support** par vol.
4.  **Taux d'échec de notification** (Objectif < 1% après retry).

## Product Scope

### MVP - Minimum Viable Product

*   **Module Réception (Chine)** : Interface saisie rapide avec intégration webcam, entrée poids et génération étiquettes QR automatique.
*   **Gestion Vols** : Groupage colis par destination, workflow validation et génération manifeste.
*   **Module Distribution (ML/CI)** : Scan arrivée, gestion stock, caisse enregistreuse avec impression reçu.
*   **Reporting** : Rapport clôture journalier PDF (encaissements + mouvements stock) envoyé automatiquement aux Admins.
*   **Moteur Notifications** : Notifications push unidirectionnelles via Wachap avec architecture queue persistante et stratégie retry garantissant livraison éventuelle lors de reconnexion.

### Growth Features (Post-MVP)

*   **Chatbot** : Intelligence conversationnelle automatisée sur WhatsApp.
*   **Paiements En Ligne** : Intégration Mobile Money dans application.
*   **Analytics Avancés** : Tableaux de bord Business Intelligence.
*   **Libre-Service Client** : Portail client pour modification destination et paiement en ligne.

### Vision (Future)

Réseau logistique entièrement automatisé où IA optimise groupages vols, clients payent instantanément via Mobile Money avant arrivée pour accélérer retrait, et analytics prédictifs aident gérer capacité entrepôt Chine.

## User Journeys

### Journey 1: Agent Chine - Réception et Expédition

**Persona:** Agent logistique en entrepôt Guangzhou/Yiwu  
**Besoin Critique:** Vitesse de traitement (environnement haute cadence)  
**Objectif:** Enregistrer colis et créer groupages aériens sans file d'attente

**Étapes:**

1. **Réception Colis**
   - Client dépose colis avec informations destinataire
   - Agent scanne QR ou saisit référence manuelle
   - Système capture photo webcam automatique
   - Agent entre poids et dimensions
   - Système génère étiquette QR unique
   - **Temps cible:** < 15 secondes par colis
   - **Notification:** Client reçoit confirmation réception immédiate via WhatsApp

2. **Constitution Vol (Groupage)**
   - Agent consulte liste colis en stock
   - Sélectionne destination (Bamako/Abidjan/autre)
   - Ajoute colis un par un au vol
   - Système calcule poids total et manifeste
   - Agent valide composition vol
   - **Résultat:** Manifeste PDF généré automatiquement

3. **Expédition**
   - Agent confirme départ vol dans système
   - Système change statut tous colis du vol en "En Transit"
   - **Notification:** Clients reçoivent notification groupée WhatsApp (ex: "Vos 3 colis sont en route vers Bamako")

**Critères de Succès:**
- Zéro file d'attente à la réception
- Tous colis du jour enregistrés avec photo
- Temps traitement moyen < 15 secondes
- Aucun colis sans étiquette QR

---

### Journey 2: Agent ML/RCI - Arrivée et Distribution

**Persona:** Agent agence locale Bamako/Abidjan  
**Besoin Critique:** Rigueur financière (zéro écart de caisse)  
**Objectif:** Distribuer colis et encaisser avec rapport exact

**Étapes:**

1. **Réception Vol**
   - Notification arrivée vol dans système
   - Agent scanne chaque colis débarqué
   - Système marque colis "Arrivé - Disponible Retrait"
   - Système identifie écarts (colis annoncés non-arrivés)
   - **Notification:** Clients avec colis arrivés reçoivent notification WhatsApp "Disponible au retrait"

2. **Remise Colis**
   - Client se présente avec pièce identité
   - Agent recherche colis par nom/téléphone/référence
   - Système affiche colis disponibles pour ce client
   - Agent scanne colis pour confirmer
   - Client paye montant dû (frais transport + douane)
   - Agent entre montant encaissé
   - Système imprime reçu
   - Agent remet colis et reçu
   - **Notification:** Client reçoit confirmation retrait WhatsApp

3. **Clôture Journalière**
   - Agent clique "Générer Rapport Journalier"
   - Système génère PDF avec:
     - Total encaissements jour
     - Liste colis remis avec montants
     - Stock restant
   - Système envoie PDF automatiquement à Super Admin
   - **Temps génération:** < 5 secondes

**Critères de Succès:**
- Zéro écart caisse (100% concordance colis sortis vs encaissements)
- Rapport PDF quotidien envoyé avant fermeture
- Aucun colis remis sans paiement
- Taux erreur scan < 1%

---

### Journey 3: Client Importateur - Suivi et Retrait

**Persona:** Commerçant ou particulier (mobile-first)  
**Besoin Critique:** Rassurance et autonomie (visibilité statut colis)  
**Objectif:** Suivre colis sans appeler agence

**Étapes:**

1. **Notification Réception Chine**
   - Client dépose marchandise chez fournisseur Chine
   - Agent Chine enregistre colis
   - Client reçoit notification WhatsApp immédiate:
     - "Colis #ABC123 reçu en entrepôt Guangzhou"
     - Lien vers portail tracking
     - Photo du colis

2. **Notification Expédition**
   - Vol constitué et validé par Agent Chine
   - Client reçoit notification groupée WhatsApp:
     - "Vos 3 colis (#ABC123, #ABC124, #ABC125) sont en route vers Bamako"
     - Date arrivée prévue
     - Numéro vol

3. **Notification Arrivée**
   - Vol arrive destination
   - Agent ML scanne colis arrivés
   - Client reçoit notification WhatsApp:
     - "Colis #ABC123 disponible au retrait"
     - Adresse agence
     - Montant à payer

4. **Tracking Autonome (Optionnel)**
   - Client clique lien dans notification
   - Portail web affiche:
     - Statut temps réel tous ses colis
     - Historique déplacements
     - Photos colis
     - Montants dus
   - **Aucun appel nécessaire**

5. **Retrait et Confirmation**
   - Client se rend agence
   - Paye et récupère colis
   - Reçoit notification finale WhatsApp:
     - "Merci pour votre confiance"
     - Reçu PDF

**Critères de Succès:**
- Réduction 50% appels "Où est mon colis ?"
- 100% notifications WhatsApp délivrées (avec retry)
- Client informé à chaque changement statut
- Moins de 1% échec notification après retry


## Domain Requirements

**Domaine:** Logistics & Transportation (Transit International Chine-Afrique)

### Traçabilité et Compliance

**DR-01: Traçabilité Bout-en-Bout**
- Système enregistre toute modification statut colis avec horodatage et utilisateur
- Historique complet accessible pour chaque colis (création → livraison)
- Traçabilité maintenue minimum 24 mois après livraison
- **Mesure:** 100% colis avec historique complet et vérifiable

**DR-02: Manifeste de Vol Conforme**
- Manifeste généré automatiquement contient: numéro vol, date, liste colis (référence, poids, destinataire)
- Format PDF imprimable pour conformité douanière
- Manifeste non-modifiable après validation
- **Mesure:** 100% vols avec manifeste conforme réglementations douanières

**DR-03: Gestion Multi-Devises**
- Système supporte Yuan (CNY) et FCFA (XOF/XAF)
- Taux de change configurable par Admin
- Factures générées dans devise destination
- **Mesure:** Zéro erreur calcul devise sur 1000 transactions

### Gestion Stocks et Inventaires

**DR-04: Intégrité Stock**
- Stock temps-réel synchronisé entre Chine et pays destinations
- Alerte automatique si écart colis annoncés vs colis scannés arrivée
- Rapprochement stock mensuel obligatoire
- **Mesure:** 100% concordance stock physique vs système

**DR-05: Audit Trail Financier**  
- Chaque transaction (paiement, remise colis) enregistrée avec horodatage, montant, agent, mode paiement
- Rapports financiers non-modifiables après clôture journalière
- Historique transactions accessible minimum 5 ans (compliance fiscale)
- **Mesure:** 100% transactions avec audit trail complet

### Sécurité Données

**DR-06: Protection Données Clients**
- Informations personnelles clients (nom, téléphone, adresse) chiffrées en base
- Accès données clients restreint par rôle (Agent ne voit que ses colis)
- Logs d'accès données sensibles
- **Mesure:** Zéro accès non-autorisé détecté par audit

**DR-07: Authentification Agents**
- Agents authentifiés par login/mot de passe avant utilisation système
- Session expirée après 8h inactivité
- Traçabilité actions par agent identifié
- **Mesure:** 100% actions système liées à agent authentifié


## Project-Type Requirements

**Type Projet:** Web Application (Multi-plateforme)

### Interface et Accessibilité

**PTR-01: Responsive Design**
- Interface adaptée automatiquement desktop (agents bureaux) et mobile (clients, agents terrain)
- Taille minimum écran supportée: 320px largeur (smartphones entrée gamme)
- Fonctionnalités critiques accessibles sur mobile sans scroll horizontal
- **Mesure:** Tests UI réussis sur Chrome/Firefox/Safari desktop + mobile

**PTR-02: Performance Interface**
- Chargement page initiale < 3 secondes sur connexion 3G
- Réponse interface utilisateur < 200ms après action (click, scan)
- Formulaires saisie optimisés pour vitesse (auto-focus, validation temps réel)
- **Mesure:** Lighthouse Performance Score > 85

### Connectivité et Fiabilité

**PTR-03: Mode Hors-Ligne Agents**
- Agents peuvent scanner colis en mode hors-ligne (données stockées localement)
- Synchronisation automatique dès reconnexion réseau
- Indicateur visuel statut connexion (en ligne/hors-ligne/en synchronisation)
- **Mesure:** 100% données scannées hors-ligne synchronisées sans perte

**PTR-04: Gestion Connexions Instables**
- Système tolère déconnexions réseau fréquentes (contexte Chine-Afrique)
- Retry automatique requêtes échouées (max 3 tentatives)
- Messages d'erreur clairs si échec définitif
- **Mesure:** < 1% perte données sur connexions instables (tests simulation)

### Sécurité Web

**PTR-05: HTTPS Obligatoire**
- Tout trafic web chiffré via HTTPS/TLS 1.3
- Certificats SSL valides pour tous domaines
- Redirection automatique HTTP → HTTPS
- **Mesure:** 100% requêtes passent par HTTPS

**PTR-06: Authentification Web Sécurisée**
- Sessions utilisateur sécurisées avec tokens JWT
- Protection CSRF sur formulaires
- Rate limiting sur endpoints authentification (anti-brute force)
- **Mesure:** Zéro vulnérabilité détectée scan sécurité OWASP Top 10

**PTR-07: Compatibilité Navigateurs**
- Support navigateurs modernes: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- Dégradation gracieuse si fonctionnalités non-supportées (webcam)
- Message d'avertissement si navigateur non-supporté
- **Mesure:** Fonctionnalités core opérationnelles sur navigateurs supportés

### Progressive Web App (PWA)

**PTR-08: Installation Progressive Web App**
- Application installable sur mobile/desktop (PWA)
- Icône app sur écran d'accueil
- Fonctionne en mode standalone (sans barre URL navigateur)
- **Mesure:** PWA installable et fonctionnelle sur Android/iOS/Desktop


## Functional Requirements

### Module Réception (Chine)

**FR-001: Enregistrement Colis**
- Agents peuvent enregistrer nouveau colis en saisissant : référence client, nom destinataire, téléphone, destination
- Système génère référence unique colis automatiquement si non fournie
- **Traçabilité:** Journey 1 Étape 1
- **Test:** Agent crée colis avec données minimales en < 5 secondes

**FR-002: Capture Photo Webcam**
- Agents peuvent capturer photo colis via webcam intégrée navigateur
- Photo associée automatiquement au colis enregistré
- Format: JPEG, résolution minimum 800x600px
- **Traçabilité:** Journey 1 Étape 1
- **Test:** Photo colis visible dans fiche colis après capture

**FR-003: Saisie Poids et Dimensions**
- Agents peuvent entrer poids (kg, 2 décimales) et dimensions (cm: L x l x h)
- Système calcule poids volumétrique automatiquement
- Validation: poids > 0 et ≤ 1000kg, dimensions > 0 et ≤ 500cm
- **Traçabilité:** Journey 1 Étape 1
- **Test:** Poids volumétrique calculé correctement selon formule (L x l x h) / 5000

**FR-004: Génération Étiquette QR**
- Système génère étiquette QR unique pour chaque colis enregistré
- QR code contient: référence colis, destination, poids
- Agents peuvent imprimer étiquette format A6 (105x148mm)
- **Traçabilité:** Journey 1 Étape 1
- **Test:** QR scanné déclenche affichage fiche colis correcte

**FR-005: Notification Réception Client**
- Système envoie notification WhatsApp client dès enregistrement colis
- Notification contient: référence colis, photo, lien tracking
- Envoi immédiat (< 30 secondes après enregistrement)
- **Traçabilité:** Journey 1 Étape 1, Journey 3 Étape 1
- **Test:** Client reçoit notification dans les 30 secondes

### Module Gestion Vols (Chine)

**FR-006: Création Vol**
- Agents peuvent créer nouveau vol en spécifiant: numéro, destination, date départ prévue
- Statut initial vol: "En Préparation"
- **Traçabilité:** Journey 1 Étape 2
- **Test:** Vol créé visible dans liste vols avec statut correct

**FR-007: Ajout Colis au Vol**
- Agents peuvent scanner QR colis pour ajouter au vol en préparation
- Système vérifie destination colis = destination vol
- Système affiche erreur si destination incompatible
- **Traçabilité:** Journey 1 Étape 2
- **Test:** Colis ajouté au vol après scan, colis mauvaise destination rejeté

**FR-008: Calcul Automatique Manifeste**
- Système calcule poids total vol (somme poids tous colis)
- Système génère liste colis avec: référence, destinataire, poids, dimensions
- Manifeste mis à jour temps réel à chaque ajout/retrait colis
- **Traçabilité:** Journey 1 Étape 2
- **Test:** Poids total vol correct après ajout 10 colis

**FR-009: Validation Vol**
- Agents peuvent valider composition vol quand préparation terminée
- Validation change statut vol: "En Préparation" → "Validé"
- Vol validé non-modifiable (colis verrouillés)
- **Traçabilité:** Journey 1 Étape 2
- **Test:** Vol validé ne permet plus ajout/retrait colis

**FR-010: Génération Manifeste PDF**
- Système génère manifeste PDF après validation vol
- PDF contient: numéro vol, date, destination, liste colis détaillée, poids total
- Format imprimable et conforme douanes
- **Traçabilité:** Journey 1 Étape 2
- **Test:** PDF généré contient tous colis vol avec informations correctes

**FR-011: Confirmation Expédition**
- Agents peuvent confirmer départ vol (après embarquement physique)
- Confirmation change statut vol: "Validé" → "En Transit"
- Confirmation change statut tous colis vol: → "En Transit"
- **Traçabilité:** Journey 1 Étape 3
- **Test:** Tous colis vol passent statut "En Transit" après confirmation

**FR-012: Notification Expédition Groupée**
- Système envoie notification WhatsApp groupée à tous clients du vol
- Notification contient: nombre colis client, numéro vol, date arrivée prévue
- Envoi immédiat après confirmation expédition
- **Traçabilité:** Journey 1 Étape 3, Journey 3 Étape 2
- **Test:** Client avec 3 colis reçoit "Vos 3 colis en route" après expédition

### Module Distribution (Mali/RCI)

**FR-013: Réception Vol Destination**
- Agents destination peuvent marquer vol "Arrivé" dans système
- Système affiche liste colis attendus pour ce vol
- **Traçabilité:** Journey 2 Étape 1
- **Test:** Liste colis vol visible après marquage arrivée

**FR-014: Scan Arrivée Colis**
- Agents peuvent scanner QR colis débarqués
- Scan change statut colis: "En Transit" → "Arrivé - Disponible Retrait"
- Système identifie colis scannés vs colis attendus (détection écarts)
- **Traçabilité:** Journey 2 Étape 1
- **Test:** Colis scanné passe statut "Disponible" et est marqué dans liste vol

**FR-015: Alerte Écarts Vol**
- Système affiche alerte si colis attendus non-scannés après 24h arrivée vol
- Liste écarts avec références colis manquants
- **Traçabilité:** Journey 2 Étape 1
- **Test:** Alerte visible si 1 colis sur 10 non-scanné après 24h

**FR-016: Notification Arrivée Client**
- Système envoie notification WhatsApp client dès scan arrivée colis
- Notification contient: référence colis, adresse agence, montant dû
- **Traçabilité:** Journey 2 Étape 1, Journey 3 Étape 3
- **Test:** Client reçoit notification dans les 30 secondes après scan arrivée

**FR-017: Recherche Colis Client**
- Agents peuvent rechercher colis par: nom client, téléphone, référence colis
- Système affiche tous colis disponibles pour ce client
- Filtrage par statut (disponible, déjà remis)
- **Traçabilité:** Journey 2 Étape 2
- **Test:** Recherche "Mamadou" retourne tous colis client avec ce nom

**FR-018: Remise Colis et Encaissement**
- Agents peuvent scanner colis pour confirmer remise physique
- Agents entrent montant encaissé (frais transport + douane)
- Système enregistre mode paiement (espèces/mobile money/autre)
- Scan remise change statut colis: "Disponible" → "Remis"
- **Traçabilité:** Journey 2 Étape 2
- **Test:** Colis statut "Remis" après scan avec montant enregistré

**FR-019: Impression Reçu**
- Système génère reçu après encaissement contenant: référence colis, montant payé, date, agent
- Reçu imprimable format ticket (80mm largeur)
- **Traçabilité:** Journey 2 Étape 2
- **Test:** Reçu imprimé contient informations correctes transaction

**FR-020: Notification Confirmation Retrait**
- Système envoie notification WhatsApp finale client après remise
- Notification contient: remerciement, reçu PDF attaché
- **Traçabilité:** Journey 2 Étape 2, Journey 3 Étape 5
- **Test:** Client reçoit notification avec PDF reçu après remise

### Module Reporting

**FR-021: Génération Rapport Journalier**
- Agents peuvent générer rapport clôture journalière en 1 clic
- Rapport PDF contient:
  - Total encaissements jour (par mode paiement)
  - Liste colis remis avec montants
  - Stock colis disponibles fin journée
- Génération < 5 secondes
- **Traçabilité:** Journey 2 Étape 3
- **Test:** PDF généré en < 5s contient tous encaissements du jour

**FR-022: Envoi Automatique Rapport Admin**
- Système envoie rapport PDF automatiquement par email à Super Admin
- Envoi immédiat après génération
- **Test:** Admin reçoit email avec PDF dans les 60 secondes

**FR-023: Historique Rapports**
- Agents peuvent consulter rapports journaliers passés (90 derniers jours)
- Téléchargement PDF rapports archivés
- **Test:** Rapport généré il y a 30 jours téléchargeable

### Module Notifications WhatsApp

**FR-024: Queue Notifications**
- Système stocke toutes notifications dans queue persistante
- Notifications conservées queue jusqu'à envoi confirmé
- **Test:** 100 notifications stockées queue restent après redémarrage système

**FR-025: Retry Automatique**
- Système retente envoi notification échouée max 3 fois
- Délai entre tentatives: 1 min, 5 min, 30 min
- **Test:** Notification échouée retentée 3 fois avec délais respectés

**FR-026: Statut Délivrabilité**
- Système enregistre statut chaque notification: envoyée, délivrée, échouée
- Admins peuvent consulter historique notifications avec statuts
- **Test:** Historique affiche statut correct pour notification test

### Module Tracking Client

**FR-027: Portail Web Tracking**
- Clients peuvent accéder portail via lien dans notification
- Portail affiche tous colis client avec statut temps réel
- Aucune authentification requise (lien avec token temporaire)
- **Traçabilité:** Journey 3 Étape 4
- **Test:** Client clique lien notification et voit liste ses colis

**FR-028: Historique Déplacements Colis**
- Portail affiche historique complet colis: réception, expédition, arrivée, remise
- Chaque étape avec date/heure
- **Traçabilité:** Journey 3 Étape 4
- **Test:** Historique colis montre 4 étapes avec horodatages

**FR-029: Affichage Photo Colis**
- Portail affiche photo colis prise à réception Chine
- **Traçabilité:** Journey 3 Étape 1, Étape 4
- **Test:** Photo visible sur portail correspond photo prise à réception


## Non-Functional Requirements

### Performance

**NFR-001: Temps Réponse API**
- API répond requêtes en < 500ms pour 95ème percentile sous charge normale
- Charge normale: 100 utilisateurs concurrents
- **Mesure:** Tests performance APM (Application Performance Monitoring)

**NFR-002: Chargement Pages**
- Pages interface agents chargent en < 2 secondes sur connexion 4G
- Pages portail client chargent en < 3 secondes sur connexion 3G
- **Mesure:** Lighthouse Performance audits

**NFR-003: Génération PDF Rapports**
- Rapport journalier PDF généré en < 5 secondes
- Manifeste vol PDF généré en < 3 secondes
- **Mesure:** Timer serveur génération PDF

**NFR-004: Recherche Colis**
- Recherche colis retourne résultats en < 1 seconde avec base 100 000 colis
- **Mesure:** Tests performance requêtes base données

### Scalabilité

**NFR-005: Volume Colis**
- Système supporte 10 000 colis actifs sans dégradation performance
- Croissance supportée: 50% augmentation annuelle
- **Mesure:** Tests charge avec 10k+ colis

**NFR-006: Utilisateurs Concurrents**
- Système supporte 50 agents travaillant simultanément
- 1000 clients consultant portail tracking simultanément
- **Mesure:** Tests charge utilisateurs concurrents

**NFR-007: Stockage Photos**
- Système stocke minimum 50 000 photos colis
- Taille moyenne photo: 500 KB
- Espace total requis: 25 GB minimum
- **Mesure:** Monitoring espace disque serveur

### Fiabilité

**NFR-008: Disponibilité Système**
- Uptime 99% pendant heures ouvrables (8h-20h heure locale)
- Heures ouvrables: Lun-Sam
- **Mesure:** Monitoring uptime serveur

**NFR-009: Intégrité Données**
- Zéro perte données colis, transactions, notifications
- Sauvegardes quotidiennes base données
- Rétention sauvegardes: 30 jours
- **Mesure:** Tests récupération backup

**NFR-010: Persistance Queue Notifications**
- Queue notifications survit redémarrages serveur (100% conservation)
- Notifications non-envoyées reprises automatiquement après redémarrage
- **Mesure:** Tests redémarrage avec notifications pending

**NFR-011: Tolérance Pannes**
- Système continue fonctionner si Wachap API indisponible (notifications queueées)
- Système continue fonctionner si impression hors-ligne (reçus imprimables plus tard)
- **Mesure:** Tests simulation pannes composants

### Sécurité

**NFR-012: Chiffrement Données Sensibles**
- Données personnelles clients chiffrées en base (AES-256)
- Communications HTTPS/TLS 1.3 minimum
- **Mesure:** Audit sécurité base données et trafic réseau

**NFR-013: Contrôle Accès Basé Rôles**
- Agent Chine: accès module Réception + Vols uniquement
- Agent ML/RCI: accès module Distribution + Reporting uniquement
- Super Admin: accès complet tous modules
- **Mesure:** Tests accès utilisateurs par rôle

**NFR-014: Audit Logging**
- Actions critiques loggées: création colis, remise, encaissement, génération rapport
- Logs contiennent: timestamp, utilisateur, action, données modifiées
- Rétention logs: 12 mois
- **Mesure:** Vérification logs après actions test

**NFR-015: Protection Injection**
- Zéro vulnérabilité injection SQL détectée
- Zéro vulnérabilité XSS détectée
- **Mesure:** Scan sécurité OWASP ZAP

### Utilisabilité

**NFR-016: Temps Formation Agents**
- Agent Chine opérationnel après < 2 heures formation
- Agent ML/RCI opérationnel après < 3 heures formation
- **Mesure:** Tests utilisabilité avec nouveaux agents

**NFR-017: Taux Erreur Saisie**
- Agents atteignent < 2% erreur saisie après 1 semaine utilisation
- **Mesure:** Monitoring erreurs validations formulaires

**NFR-018: Accessibilité Mobile**
- Portail client utilisable sur smartphones minimum iOS 12+ / Android 8+
- Toutes fonctionnalités accessibles sans zoom horizontal
- **Mesure:** Tests manuels dispositifs cibles

**NFR-019: Support Langues**
- Interface système disponible français (langue principale)
- Messages notifications WhatsApp en français
- **Mesure:** Vérification textes interface et notifications

### Maintenabilité

**NFR-020: Temps Récupération Panne**
- Système restauré en < 4 heures après panne majeure
- Backup base données récupérable en < 1 heure
- **Mesure:** Tests plan reprise activité (DRP)

**NFR-021: Monitoring Système**
- Métriques clés monitorées temps réel: CPU, RAM, espace disque, temps réponse API
- Alertes automatiques si seuils dépassés
- **Mesure:** Dashboard monitoring opérationnel










