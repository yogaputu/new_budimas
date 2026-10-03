import api from './axios';

export function syncFleetTrips(payload = {}) {
  return api.post('/api/fleet-management/trips/sync', payload);
}

export function getFleetManagementOverview(params = {}) {
  return api.get('/api/fleet-management/overview', { params });
}

export function getFleetTripGpsHistory(idTrip) {
  return api.get(`/api/fleet-management/trips/${idTrip}/gps`);
}

// Supervisory POD view.  The mobile app has its own scoped route; this route
// is used by the ERP fleet-monitoring screen after an authorised user opens a
// manifest trip.
export function getFleetTripStops(idTrip) {
  return api.get(`/api/fleet-management/trips/${idTrip}/stops`);
}

// POD evidence is intentionally served by an authenticated endpoint.  Keeping
// this request inside the shared Axios client ensures the ERP bearer token is
// attached before a browser object URL is created by the view.
export function getFleetTripStopEvidence(resourceUrl) {
  return api.get(resourceUrl, { responseType: 'blob' });
}

export function startFleetTrip(idTrip, payload = {}) {
  return api.post(`/api/fleet-management/trips/${idTrip}/start`, payload);
}

export function completeFleetTrip(idTrip, payload = {}) {
  return api.post(`/api/fleet-management/trips/${idTrip}/complete`, payload);
}

export function getFleetMaintenances(params = {}) {
  return api.get('/api/fleet-management/maintenance', { params });
}

export function createFleetMaintenance(payload = {}) {
  return api.post('/api/fleet-management/maintenance', payload);
}
