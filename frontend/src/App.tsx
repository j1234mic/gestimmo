import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuthStore } from './store/authStore'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Properties from './pages/Properties'
import GenericModule from './pages/GenericModule'

function App() {
  const checkAuth = useAuthStore(s => s.checkAuth)

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/properties/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Properties />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/owners"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Propriétaires" module="Module 2" apiPath="/owners" description="Fiches personne physique/morale, mandats, signature électronique, compta par bien, portail JWT." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/tenants"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Locataires" module="Module 3" apiPath="/tenants" description="Fiche complète, candidature en ligne, garanties, portail locataire JWT, solvabilité, impayés." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/leases"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Baux & Contrats" module="Module 4" apiPath="/leases" description="8 types de bail, modèles versionnés, PDF, signature, révisions IRL/ICC, congés, EDL." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/finance"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Finance & Comptabilité" module="Module 5" apiPath="/finance" description="Appels de loyer auto, encaissement multi-canal, impayés J+5..J+90, charges, FEC, balance." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/maintenance"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Maintenance & Travaux" module="Module 6" apiPath="/maintenance/tickets" description="Ticketing, workflow validation, prestataires, préventif, Gantt, QC, budget par bien." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/condo"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Copropriété" module="Module 7" apiPath="/condo" description="Lots, tantièmes, AG, budget, appels de fonds, travaux, prestataires copro." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/crm"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="CRM & Commercial" module="Module 8" apiPath="/crm/prospects" description="Prospects, pipeline Kanban, visites, matching auto prospect↔bien, diffusion portails." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/reporting"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Reporting" module="Module 9" apiPath="/reporting" description="Dashboard KPIs, widgets drag&drop, rapports prédéfinis/personnalisés, exports PDF/Excel/Word." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/comms"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Communication" module="Module 10" apiPath="/communications" description="Messagerie interne, notifications multicanal, automatisation, préférences, historique." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/ged"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="GED" module="Module 11" apiPath="/ged/documents" description="Arborescence, upload lot, 11 modèles auto, signature, OCR, recherche plein texte, RGPD." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/geolocation"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Géolocalisation" module="Module 13" apiPath="/geolocation" description="Carte interactive, clustering, zones, proximité, calcul itinéraire, export." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/extension"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Extension Immobilière (18-31)" module="Modules 18-31" apiPath="/extension" description="Courte durée, contentieux, fiscalité, financement, portail public, services, clés, compteurs, VEFA, SCPI, rénovation, satisfaction, tâches, sourcing." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <Layout>
                <GenericModule title="Administration & Sécurité" module="Module 12" apiPath="/admin/users" description="RBAC granulaire, 2FA TOTP/email/SMS, SSO OAuth2/SAML, multi-sociétés, audit, backup, RGPD." />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
