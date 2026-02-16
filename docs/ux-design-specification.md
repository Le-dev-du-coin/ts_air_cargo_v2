---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: ['_bmad-output/planning-artifacts/prd.md', '_bmad-output/planning-artifacts/product-brief-ts_air_cargo_v2-2026-02-06.md']
workflowType: 'ux-design'
projectName: 'ts_air_cargo_v2'
---

# UX Design Specification ts_air_cargo_v2

**Author:** MaliandevBoy
**Date:** 2026-02-10

---

<!-- UX design content will be appended sequentially through collaborative workflow steps -->

## Executive Summary

### Project Vision

ts_air_cargo_v2 digitalise la gestion logistique pour agences de transit opérant sur le corridor Chine-Afrique de l'Ouest. La plateforme remplace une gestion manuelle Excel par une solution centralisée offrant traçabilité complète, du dépôt en Chine (Guangzhou/Yiwu) jusqu'à la livraison finale à Bamako ou Abidjan. En automatisant la facturation, le groupage aérien et le suivi client via WhatsApp, elle transforme une opération artisanale en processus logistique professionnel.

### Target Users

**7 interfaces utilisateur distinctes** organisées en 3 catégories :

**Agents Opérationnels (3)**
- **Agent Chine** : Besoin critique de vitesse (< 15s par colis) - Module Réception + Gestion Vols
- **Agent Mali** : Besoin rigueur financière - Module Distribution + Caisse + Reports PDF
- **Agent Côte d'Ivoire** : Besoin rigueur financière - Module Distribution + Caisse + Reports PDF

**Administrateurs (3)**
- **Admin Chine** : Besoin visibilité temps réel - Dashboard supervision + validation vols
- **Admin Mali** : Besoin contrôle financier - Dashboard pays + analytics
- **Admin Côte d'Ivoire** : Besoin contrôle financier - Dashboard pays + analytics

**Utilisateurs Externes (1)**
- **Client Importateur** : Besoin rassurance et autonomie - Portail Web mobile + notifications WhatsApp

### Key Design Challenges

1. **Multi-Interface Complexity** : 7 interfaces avec besoins différents (vitesse vs analytics) nécessitant cohérence visuelle mais optimisation spécifique
2. **Performance Critique** : Interface Agent Chine doit permettre traitement < 15 secondes (webcam + scan + pesée)
3. **Rigueur Financière** : Interface caisse Mali/RCI doit guider vers exactitude (zéro écart) sans ralentir workflow
4. **Mobile-First Client** : Portail tracking optimisé smartphones et connexions 3G/4G faibles
5. **Scalabilité Multi-Pays** : Architecture i18n pour langues futures (français + langues locales potentielles)

### Design Opportunities

1. **Workflow Visual Feedback** : Feedback instantané et animations micro pour créer confiance et rapidité perçue
2. **Dashboard Data Visualization** : Visualisations élégantes temps réel (vols, stocks, finance) pour Admins
3. **Progressive Disclosure** : Navigation contextuelle montrant seulement ce dont chaque rôle a besoin
4. **Offline-First Mobile** : UX résiliente avec synchronisation automatique pour agents perdant connexion

## Core User Experience

### Defining Experience

**ts_air_cargo_v2** est définie par **7 workflows distincts optimisés** pour chaque rôle :

**Agents Opérationnels**
- **Agent Chine** : Workflow ultra-rapide (< 15s) : Scan → Capture webcam → Pesée → Confirmation visuelle
- **Agent Mali/RCI** : Workflow précis : Scan arrivée → Vérification montant → Encaissement → Impression reçu

**Administrateurs**
- **Admin Chine** : Dashboard temps réel → Validation vols groupés → Génération manifeste
- **Admin Mali/RCI** : Dashboard financier → Vérification rapports agents → Analytics pays

**Clients**
- **Client Mobile** : Clic lien WhatsApp → Tracking visuel colis → Informations retrait

### Platform Strategy

**Web Application Responsive**
- Desktop-first pour Agents/Admins (écrans larges, clavier/souris)
- Mobile-first pour Clients (smartphones, touch)
- Progressive Web App (PWA) installable pour agents terrain

**Capabilities Techniques**
- WebRTC/MediaDevices API pour webcam (browser natif, pas d'app dédiée)
- Offline-first avec IndexedDB pour agents (sync auto au retour connexion)
- Optimisation 3G/4G pour portail client Mali/Côte d'Ivoire

**Multi-Plateforme**
- Chrome/Firefox/Safari support (agents desktop)
- iOS/Android browsers (clients mobile)
- Pas d'app native requise (réduction coûts développement)

### Effortless Interactions

**Zero-Friction Actions**
1. **Agent Chine** : Scan QR auto-focus → Webcam 1-click → Pesée auto-détection → Étiquette auto-print
2. **Agent Mali/RCI** : Montant auto-calculé → Confirmation visuelle avant encaissement → Reçu auto-généré
3. **Admin** : Dashboards auto-refresh → Validation batch (sélection multiple) → Export PDF 1-click
4. **Client** : Tracking sans login → Notifications push → Partage lien colis

**Élimination Points Friction**
- Pas de saisie manuelle référence (QR scan automatique)
- Pas de calcul manuel montant (auto depuis base données)
- Pas de recherche documents (notifications avec liens directs)
- Pas de double-saisie (données partagées entre modules)

### Critical Success Moments

**Moments Make-or-Break**

**Agent Chine - First 15 Seconds**
- Feedback visuel instantané scan réussi (✓ vert + son)
- Photo webcam preview avant validation
- Confirmation "Colis enregistré" avec référence

**Agent Mali/RCI - Moment Encaissement**
- Montant affiché clairement AVANT paiement
- Validation double-check (montant client vs système)
- Reçu imprimé instantanément après paiement

**Admin - Validation Vol**
- Vue liste colis groupés avec totaux (poids/volume/nombre)
- Validation 1-click → Manifeste PDF généré
- Notifications clients envoyées automatiquement

**Client - Notification Arrivée**
- Message WhatsApp clair "Colis disponible au retrait"
- Lien direct tracking avec adresse agence + montant
- Pas de login requis pour voir statut

### Experience Principles

**Principes Guidant Toutes Décisions UX**

1. **Speed First** : Chaque action agent doit être < 3 secondes (objectif) ou fournir feedback immédiat
2. **Zero Errors Financial** : Interface guide vers exactitude (montants clairs, confirmations visuelles, double-check)
3. **Mobile-Optimized Client** : Portail client fonctionne parfaitement sur smartphones 3G/4G faibles
4. **Offline Resilience** : Agents jamais bloqués par perte connexion (queue locale, sync auto)
5. **Progressive Disclosure** : Montrer seulement ce dont l'utilisateur a besoin pour sa tâche actuelle
6. **Instant Feedback** : Toute action utilisateur reçoit réponse visuelle immédiate (loading, success, error)
7. **Context-Aware Navigation** : Navigation s'adapte au rôle (Agent voit opérations, Admin voit analytics)

## Desired Emotional Response

### Primary Emotional Goals

**Agent Chine: Efficience Maîtrisée**
"Chaque colis traité en < 15s avec confiance totale que rien n'est oublié. Je maîtrise le flux, rien ne me ralentit."

**Agent Mali/RCI: Sérénité Financière**  
"Zéro stress à la clôture - je sais que ma caisse sera juste. L'interface me guide vers l'exactitude."

**Admins: Visibilité & Contrôle**
"Vue d'ensemble complète en temps réel. Je prends des décisions basées sur data fiable."

**Client: Rassurance & Autonomie**
"Je sais exactement où est mon colis sans appeler personne. Je suis autonome."

### Emotional Journey Mapping

**Découverte (Premier Contact)**
- **Agent** : Curiosité → "Est-ce vraiment plus rapide qu'Excel ?"
- **Client** : Scepticisme → "Vont-ils vraiment me notifier ?"

**Core Action (Utilisation)**
- **Agent Chine** : Flow state → Feedback instantané crée rythme naturel
- **Agent Mali/RCI** : Confiance croissante → Montants auto justes = tranquillité
- **Admin** : Contrôle → Dashboard live donne visibilité totale
- **Client** : Soulagement → Notification WhatsApp confirme colis reçu

**Après Tâche (Complétion)**
- **Agent** : Satisfaction → "J'ai terminé ma journée sans stress"
- **Admin** : Assurance → "Tous les indicateurs sont au vert"
- **Client** : Anticipation positive → "Je vais recevoir mon colis bientôt"

**En Cas d'Erreur**
- **Tous** : Guidage calme → Messages clairs expliquent problème + solution
- **Pas de panique** : Erreurs rattrapables, pas de perte de données

### Micro-Emotions

**Confiance vs. Confusion**
✅ Confiance via feedback visuel instantané (✓ vert, animations fluides)  
❌ Éviter confusion via progressive disclosure (pas de surcharge info)

**Accomplissement vs. Frustration**
✅ Accomplissement via confirmations claires après chaque action  
❌ Éviter frustration via workflows optimisés (minimal clicks)

**Sérénité vs. Anxiété**
✅ Sérénité via double-checks automatiques (montants, totaux)  
❌ Éviter anxiété via reports PDF auto-générés (pas de calculs manuels)

**Autonomie vs. Dépendance**
✅ Autonomie client via tracking sans login + notifications proactives  
❌ Éviter dépendance via portail self-service (pas besoin d'appeler)

### Design Implications

**Pour Créer Efficience Maîtrisée (Agent Chine)**
- Scan QR auto-focus dès ouverture page
- Webcam 1-click capture (pas de menus)
- Pesée auto-détection (pas de saisie manuelle)
- Animations micro feedback (✓ vert + son confirmation)

**Pour Créer Sérénité Financière (Agent Mali/RCI)**
- Montants affichés LARGE et CLAIR avant encaissement
- Color-coding (vert = OK, orange = à vérifier)
- Confirmations double-check ("Montant correct ? 25 000 FCFA")
- Rapport PDF auto avec totaux vérifiables

**Pour Créer Visibilité & Contrôle (Admins)**
- Dashboards auto-refresh (live data)
- Charts interactifs (drill-down sur anomalies)
- Validation batch (sélection multiple vols)
- Exports 1-click (PDF/Excel)

**Pour Créer Rassurance & Autonomie (Client)**
- Tracking visuel (timeline graphique statut colis)
- Notifications WhatsApp proactives (4 étapes clés)
- Pas de login requis (lien direct depuis notif)
- Photos colis visible (preuve réception Chine)

### Emotional Design Principles

1. **Feedback Immédiat = Confiance** : Toute action reçoit réponse visuelle < 300ms
2. **Clarté Financière = Sérénité** : Montants toujours visibles avant validation
3. **Autonomie = Rassurance** : Client accède info sans intermédiaire
4. **Simplicité = Flow** : Workflow naturel sans réflexion cognitive
5. **Guidage = Zéro Stress** : Interface prévient erreurs plutôt que corriger après

## UX Pattern Analysis & Inspiration

### Inspiring Products Analysis

**1. Shopify Admin** (E-commerce Backend)
- **Excellence** : Dashboard temps réel avec KPIs clairs, actions rapides (fulfill order 2 clicks)
- **Patterns Pertinents** : Bulk actions (validation batch vols), status pills (color-coded), search filters puissants
- **Lesson** : Backend opérationnel doit privilégier vitesse sur esthétique pure

**2. Linear** (Issue Tracking)
- **Excellence** : Keyboard shortcuts partout, feedback instantané (< 100ms), offline-first impeccable
- **Patterns Pertinents** : Cmd+K command palette, optimistic UI updates, animations micro subtiles
- **Lesson** : Speed perception via feedback immédiat même si async

**3. ShipStation** (Logistics Software)
- **Excellence** : Scan-centric workflow, batch printing labels, tracking status visual timeline
- **Patterns Pertinents** : Barcode scan auto-focus, print queues, status tracking visuel
- **Lesson** : Logistics apps doivent optimiser pour hardware (scanners, printers)

**4. WhatsApp Business** (Client Communication)
- **Excellence** : Notifications push efficaces, liens directs sans login, interface mobile familière
- **Patterns Pertinents** : Deep linking, media preview (photos), read receipts
- **Lesson** : Mobile messaging comme notification layer (pas besoin app dédiée)

### Transferable UX Patterns

**Navigation Patterns**
- **Sidebar Role-Aware** (Shopify-inspired) : Navigation contextuelle Agent vs Admin
- **Command Palette** (Linear-inspired) : Cmd+K pour agents avancés (scan rapide référence)
- **Mobile Bottom Tabs** (WhatsApp-inspired) : Navigation client simple (Tracking, Notifications, Profil)

**Interaction Patterns**
- **Scan Auto-Focus** (ShipStation-inspired) : Page réception auto-focus champ scan au chargement
- **Bulk Actions** (Shopify-inspired) : Checkbox multi-select + actions batch (valider 10 vols simultanément)
- **Optimistic UI** (Linear-inspired) : Feedback visuel immédiat avant confirmation serveur
- **Media Preview** (WhatsApp-inspired) : Photos colis cliquables pour zoom fullscreen

**Visual Patterns**
- **Status Pills** (Shopify-inspired) : Color-coded status colis (Reçu=bleu, En route=orange, Livré=vert)
- **Timeline Tracking** (ShipStation-inspired) : Visualisation chronologique étapes colis
- **Data Tables Dense** (Shopify-inspired) : Listes compactes pour agents (max info minimal scroll)
- **Card-Based Mobile** (WhatsApp-inspired) : Cards colis sur mobile client (touch-friendly)

### Anti-Patterns to Avoid

**1. Multi-Step Wizards pour Actions Simples**
- ❌ Amazon-style checkout (5 steps) pour encaissement simple
- ✅ Single-page caisse avec confirmations inline

**2. Login Obligatoire Client**
- ❌ Demander création compte pour tracking
- ✅ Liens directs WhatsApp (magic links)

**3. Dashboards Surchargés**
- ❌ 20 widgets simultanés (paralysie décisionnelle)
- ✅ KPIs essentiels + drill-down optionnel

**4. Notifications Email Uniquement**
- ❌ Compter sur emails (faible open rate Mali/RCI)
- ✅ WhatsApp comme canal principal

**5. Saisie Manuelle Quand Scan Possible**
- ❌ Form fields pour références existantes
- ✅ QR scan automatique + fallback manuel

### Design Inspiration Strategy

**Patterns à Adopter Directement**
- ✅ Status pills color-coded (Shopify) → Clarté instantanée statut
- ✅ Auto-focus scan inputs (ShipStation) → Vitesse Agent Chine
- ✅ WhatsApp deep links (WhatsApp Business) → Autonomie client
- ✅ Optimistic UI updates (Linear) → Perception vitesse

**Patterns à Adapter**
- 🔄 Command palette (Linear) → Simplifier pour clavier-only agents avancés (optionnel)
- 🔄 Bulk actions (Shopify) → Adapter pour validation vols groupés
- 🔄 Timeline tracking (ShipStation) → Simplifier pour 4 étapes clés (pas 15)

**Patterns à Éviter**
- ❌ Multi-step wizards → Workflows agents doivent être single-page
- ❌ Email notifications → WhatsApp primary, email backup seulement
- ❌ Complex filters (20 options) → Keep simple (date, destination, statut)

## Design System Strategy

### Design System Approach

**Choix Recommandé: Tailwind CSS + shadcn/ui**

**Rationale**
- **Tailwind CSS** : Utility-first permet customization totale sans CSS custom
- **shadcn/ui** : Composants React headless copiables (pas de dépendance npm) basés Radix UI
- **Avantages** :
  - Pas de vendor lock-in (code owns composants)
  - Accessibilité built-in (Radix primitives)
  - Dark mode trivial (Tailwind)
  - Performance (pas de runtime CSS-in-JS)
  - Developer velocity (composants pre-built customizables)

**Alternative Considérée: Material UI**
- ✅ Composants riches out-of-the-box
- ❌ Opinion design forte (Material), customization difficile
- ❌ Bundle size important
- **Verdict** : Non recommandé (besoin design custom logistique, pas Material consumer)

### Color Palette Strategy

**Semantic Colors (Status)**
- **Info (Bleu)** : `#3B82F6` - Colis reçu Chine
- **Warning (Orange)** : `#F59E0B` - En transit / Action requise
- **Success (Vert)** : `#10B981` - Livré / Validation OK
- **Error (Rouge)** : `#EF4444` - Problème / Erreur
- **Neutral (Gris)** : `#6B7280` - Textes secondaires

**Brand Colors**
- **Primary** : `#2563EB` (Bleu professionnel logistique)
- **Secondary** : `#F59E0B` (Orange accentuation)
- **Background** : `#F9FAFB` (Light mode), `#111827` (Dark mode)

### Typography Strategy

**Font Stack**
- **Primary** : `Inter` (Google Fonts) - Moderne, lisible, variable font
- **Monospace** : `JetBrains Mono` - Codes, références colis, manifestes

**Sizes (Tailwind Scale)**
- **Headers** : `text-2xl` (24px) à `text-4xl` (36px)
- **Body** : `text-base` (16px) desktop, `text-sm` (14px) mobile
- **Captions** : `text-xs` (12px) metadata

**Weights**
- **Regular** : 400 (body text)
- **Medium** : 500 (labels, buttons)
- **Semibold** : 600 (headers)
- **Bold** : 700 (critical data, montants)

### Component Architecture

**Core Components to Build**
1. **StatusPill** : Badge color-coded status colis
2. **DataTable** : Table dense avec sort/filter pour agents
3. **ScanInput** : Input auto-focus avec QR icon
4. **CardColis** : Card mobile client avec photo + tracking
5. **DashboardKPI** : Widget KPI avec trend indicator
6. **ConfirmationModal** : Modal double-check actions critiques (encaissement)
7. **NotificationToast** : Toast feedback actions (✓ Colis enregistré)

**Layout Components**
1. **SidebarNav** : Navigation role-aware (Agent vs Admin)
2. **MobileBottomNav** : Tabs navigation client mobile
3. **PageHeader** : Header avec breadcrumb + actions contextuelles
4. **EmptyState** : État vide avec illustrations + CTA

### Responsive Strategy

**Breakpoints (Tailwind Defaults)**
- **Mobile** : < 640px (Client portail)
- **Tablet** : 640px - 1024px (Agents terrain)
- **Desktop** : > 1024px (Agents/Admins bureaux)

**Approach**
- **Mobile-First Client** : Design portail client pour mobile d'abord
- **Desktop-First Agents/Admins** : Interfaces opérationnelles optimisées larges écrans

### Accessibility Requirements

**WCAG 2.1 Level AA Compliance**
- **Contrast** : 4.5:1 minimum texte, 3:1 UI components
- **Keyboard Navigation** : Tous workflows accessibles clavier (Tab, Enter, Esc)
- **Screen Readers** : ARIA labels sur actions critiques
- **Focus Indicators** : Visible focus states (ring-2 ring-primary)

**Specific Considerations**
- **Color-Blind Safe** : Statut pas uniquement couleur (icons + text)
- **Large Touch Targets** : 44x44px minimum mobile (Apple HIG)
- **Skip Links** : "Skip to main content" pour agents clavier-only
