---
stepsCompleted: [1, 2, 3, 4, 5]
inputDocuments: []
date: 2026-02-06
lastRevised: 2026-02-10
revisedSections: ['Target Users', 'User Journey']
author: MaliandevBoy
---

# Product Brief: ts_air_cargo_v2

## Executive Summary

ts_air_cargo_v2 est une plateforme de gestion logistique intégrée conçue pour les agences de transit opérant sur le corridor Chine-Afrique de l'Ouest. Elle remplace la gestion manuelle sur Excel par une solution centralisée offrant une traçabilité totale, de la réception en entrepôt en Chine jusqu'à la livraison finale. En automatisant la facturation, le groupage aérien et le suivi client, elle transforme une opération artisanale en un processus logistique professionnel et transparent.

---

## Core Vision

### Problem Statement

L'agence gère actuellement des flux complexes de marchandises à l'aide de fichiers Excel déconnectés. Cette approche manuelle entraîne une visibilité limitée sur les stocks en entrepôt, des difficultés à organiser les groupages aériens (vols), une gestion financière fastidieuse, et une surcharge du service client faute d'outils de suivi pour les clients.

### Problem Impact

*   **Inefficacité** : Perte de temps sur la saisie Excel et la recherche d'informations éparpillées.
*   **Expérience Client** : Clients frustrés par le manque de visibilité, obligeant à des appels constants pour le statut.
*   **Risques Opérationnels** : Erreurs potentielles dans la gestion des stocks et l'organisation des colis et des vols.

### Why Existing Solutions Fall Short

*   **Excel** : Statique, manuel, risque d'erreurs élevé, pas de partage temps réel avec le client.
*   **Solutions Génériques** : Souvent inadaptées aux spécificités du "groupage" aérien et du transit Chine-Afrique.

### Proposed Solution

Une application web unifiée pour digitaliser l'agence :
1.  **Gestion Opérationnelle** : Suivi des stocks, organisation des colis et gestion complète des vols/groupages.
2.  **Portail Client** : Site web permettant aux clients de suivre leurs colis en autonomie.
3.  **Module Financier** : Gestion intégrée des factures et des paiements.

### Key Differentiators

*   **Visibilité de Bout en Bout** : Du dépôt en Chine à la main du client à Bamako/Abidjan.
*   **Centralisation** : Logistique (colis/vols) et Finance unifiées pour éviter la double saisie.

## Target Users

### Agents Opérationnels (Gestion Entrepôt)

#### 1. Agent Chine
*   **Contexte** : Entrepôt source Chine (Guangzhou/Yiwu). Environnement haute cadence.
*   **Responsabilités** : Réception colis, pesée/mesure, prise photo webcam, étiquetage QR, constitution vols (groupage).
*   **Interface** : Module Réception + Module Gestion Vols.
*   **Besoin Critique** : **Vitesse** - Temps traitement < 15 secondes par colis (scan + photo + pesée).
*   **Succès** : "Zéro file d'attente à la réception et tous les colis du jour sont dans le système avec photo."

#### 2. Agent Mali
*   **Contexte** : Entrepôt destination Bamako.
*   **Responsabilités** : Pointage arrivées vol, gestion stock local, remise colis, encaissement.
*   **Interface** : Module Distribution + Module Caisse.
*   **Besoin Critique** : **Rigueur Financière** - Rapport journalier PDF fiable pour justifier la caisse.
*   **Succès** : "Ma caisse correspond exactement aux colis sortis et j'ai envoyé mon rapport en 1 clic."

#### 3. Agent Côte d'Ivoire
*   **Contexte** : Entrepôt destination Abidjan.
*   **Responsabilités** : Pointage arrivées vol, gestion stock local, remise colis, encaissement.
*   **Interface** : Module Distribution + Module Caisse.
*   **Besoin Critique** : **Rigueur Financière** - Rapport journalier PDF fiable pour justifier la caisse.
*   **Succès** : "Ma caisse correspond exactement aux colis sortis et j'ai envoyé mon rapport en 1 clic."

### Administrateurs (Supervision)

#### 4. Admin Chine
*   **Contexte** : Supervision globale entrepôt Chine.
*   **Responsabilités** : Validation vols, suivi performance équipe, analytics stocks Chine.
*   **Interface** : Dashboard Chine + Rapports consolidés entrepôt.
*   **Besoin Critique** : **Visibilité** - Vue d'ensemble opérations Chine en temps réel.

#### 5. Admin Mali
*   **Contexte** : Supervision agence Mali.
*   **Responsabilités** : Suivi financier Mali, validation rapports agents, analytics pays.
*   **Interface** : Dashboard Mali + Rapports consolidés pays.
*   **Besoin Critique** : **Contrôle Financier** - Vérification concordance caisse/colis par agence.

#### 6. Admin Côte d'Ivoire
*   **Contexte** : Supervision agence Côte d'Ivoire.
*   **Responsabilités** : Suivi financier Côte d'Ivoire, validation rapports agents, analytics pays.
*   **Interface** : Dashboard Côte d'Ivoire + Rapports consolidés pays.
*   **Besoin Critique** : **Contrôle Financier** - Vérification concordance caisse/colis par agence.

### Utilisateurs Externes

#### 7. Client Importateur
*   **Contexte** : Commerçant ou particulier. Mobile-first (smartphones).
*   **Responsabilités** : Suivi autonome de ses colis sans appeler l'agence.
*   **Interface** : Portail Web Tracking + Notifications WhatsApp avec liens.
*   **Besoin Critique** : **Rassurance** - Savoir où est son colis à tout moment.
*   **Interaction** : 
    *   *Réception Chine* : Notification immédiate "Colis #ABC123 reçu" + photo + lien tracking.
    *   *Expédition* : Notification groupée "Vos 3 colis (#ABC123, #ABC124, #ABC125) en route vers Bamako".
    *   *Arrivée Destination* : Notification "Colis #ABC123 disponible au retrait" + adresse agence + montant dû.
    *   *Confirmation Retrait* : Notification finale "Merci pour votre confiance" + reçu PDF.

### User Journey (Flux de Notification)

1.  **Enregistrement (Chine)** : Agent Chine scan + photo webcam → **Notif 1** (Immédiate) : "Colis reçu en entrepôt Guangzhou" + photo + lien tracking.
2.  **Expédition (Chine)** : Admin Chine valide vol → **Notif 2** (Groupée/Intelligente) : "Vos 3 colis sont en route vers Bamako" + numéro vol + date arrivée prévue.
3.  **Arrivée (Mali/RCI)** : Agent Mali/RCI scanne colis débarqués → **Notif 3** : "Colis disponible au retrait" + adresse agence + montant à payer.
4.  **Livraison (Mali/RCI)** : Agent encaisse et remet colis → **Notif 4** : "Merci pour votre confiance" + reçu PDF.

## Success Metrics

### User Success Metrics
*   **Agent Chine (Vitesse)** : Enregistrement d'un colis (Scan + Photo + Pesée) en **moins de 15 secondes**.
*   **Agent Mali/RCI (Sérénité)** : **Zéro écart de caisse** lors de la clôture journalière grâce au rapport automatisé.
*   **Client (Autonomie)** : Réduction de **50% des appels entrants** pour demander "Où est mon colis ?".

### Business Objectives
*   **Scalabilité** : Capacité à traiter **2x plus de volume** sans recruter de personnel administratif supplémentaire.
*   **Protection des Revenus** : Élimination des colis perdus ou non-facturés grâce à la traçabilité de bout en bout.
*   **Fiabilité Technique (Wachap)** : **100% de délivrabilité** des notifications grâce à un système de file d'attente (Queue & Retry) qui gère les déconnexions WhatsApp.

### Key Performance Indicators (KPIs)
1.  **Temps de traitement moyen** par colis (Réception).
2.  **Taux de colis livrés** vs colis reçus (Objectif 100%).
3.  **Nombre de tickets/appels support** par vol.
4.  **Taux d'échec de notification** (Objectif < 1% après retry).

## MVP Scope

### Core Features (MVP 1.0)
*   **Reception Module (China)**: Fast entry interface with Webcam integration, weight entry, and auto-generated QR labels.
*   **Flight Management**: Grouping parcels into flights, validation workflow, and manifest generation.
*   **Distribution Module (ML/CI)**: Arrival scanning, stock management, and cash register with receipt printing.
*   **Reporting**: Daily closing PDF report (Cash + Stock movements) sent specifically to Admins.
*   **Notification Engine**: One-way Push notifications via Wachap API (Queue & Retry architecture). **Strategy**: Wait for reconnection on failure, ensuring eventually consistent delivery.

### Out of Scope for MVP
*   **Chatbot**: No automated conversational AI on WhatsApp (V2).
*   **Online Payments**: No Mobile Money integration (Cash only for MVP).
*   **Complex Analytics**: No Business Intelligence dashboards (Daily PDF only).
*   **Client Self-Service**: No ability for clients to edit destination or pay online.
*   **SMS Fallback**: Decision to rely solely on WhatsApp reconnection logic.

### MVP Success Criteria
*   **Operational**: The system successfully tracks 100% of parcels from China to Delivery without data loss.
*   **Financial**: Daily cash reports match physical cash in 100% of agencies for 30 consecutive days.
*   **Technical**: Wachap connection self-heals after disconnection; 0% message loss in the queue.

### Future Vision
A fully automated logistics network where AI optimizes flight grouping, clients pay instantly via Mobile Money before arrival to speed up pickup, and predictive analytics help manage warehouse capacity in China.
