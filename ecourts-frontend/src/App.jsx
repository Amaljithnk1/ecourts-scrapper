import React, { useState, useEffect } from 'react';
import { Download, Search, Calendar, MapPin, FileText, AlertCircle, CheckCircle, Loader2, RefreshCw, BarChart3 } from 'lucide-react';

const API_BASE = 'http://localhost:5000/api';

export default function ECourtsScraper() {
  const [states, setStates] = useState([]);
  const [districts, setDistricts] = useState([]);
  const [complexes, setComplexes] = useState([]);
  const [courts, setCourts] = useState([]);

  const [selectedState, setSelectedState] = useState('');
  const [selectedDistrict, setSelectedDistrict] = useState('');
  const [selectedComplex, setSelectedComplex] = useState('');
  const [selectedCourt, setSelectedCourt] = useState('');
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [caseKind, setCaseKind] = useState('civ');

  const [cnr, setCnr] = useState('');
  const [causeList, setCauseList] = useState(null);
  const [caseDetails, setCaseDetails] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [statsData, setStatsData] = useState(null);
  const [captchaSrc, setCaptchaSrc] = useState('');
  const [captchaCode, setCaptchaCode] = useState('');
  const [filter, setFilter] = useState('');

  const selectedCourtName = courts.find(c => c.code === selectedCourt)?.name || '';

  useEffect(() => {
    fetchStates();
    refreshCaptcha();
  }, []);

  const handleApiError = async (res) => {
    try {
      const ct = res.headers.get('Content-Type') || '';
      if (ct.includes('application/json')) {
        const j = await res.json();
        const msg = j.message || 'Request failed';
        if ((j.code || '').toUpperCase() === 'INVALID_CAPTCHA' || /captcha/i.test(msg)) {
          await refreshCaptcha();
          setCaptchaCode('');
        }
        showError(msg);
      } else {
        const t = await res.text();
        if (/captcha/i.test(t)) {
          await refreshCaptcha();
          setCaptchaCode('');
        }
        showError(t || 'Request failed');
      }
    } catch {
      showError('Request failed');
    }
  };

  const refreshCaptcha = async () => {
    try {
      const res = await fetch(`${API_BASE}/captcha?module=cause_list&t=${Date.now()}`, { cache: 'no-store' });
      const ct = res.headers.get('Content-Type') || '';
      if (!res.ok || !ct.startsWith('image/')) {
        showError('Captcha server error. Try again in a minute.');
        return;
      }
      const blob = await res.blob();
      if (captchaSrc) URL.revokeObjectURL(captchaSrc);
      setCaptchaSrc(URL.createObjectURL(blob));
      setCaptchaCode('');
    } catch {
      showError('Failed to load captcha');
    }
  };

  const fetchStates = async () => {
    try {
      const res = await fetch(`${API_BASE}/states`);
      const data = await res.json();
      if (data.success) setStates(data.data);
    } catch {
      showError('Failed to fetch states');
    }
  };

  const fetchDistricts = async (stateCode) => {
    try {
      const res = await fetch(`${API_BASE}/districts?state_code=${stateCode}`);
      const data = await res.json();
      if (data.success) setDistricts(data.data);
    } catch {
      showError('Failed to fetch districts');
    }
  };

  const fetchComplexes = async (stateCode, distCode) => {
    try {
      const res = await fetch(`${API_BASE}/complexes?state_code=${stateCode}&dist_code=${distCode}`);
      const data = await res.json();
      if (data.success) setComplexes(data.data);
    } catch {
      showError('Failed to fetch complexes');
    }
  };

  const fetchCourts = async (stateCode, distCode, complexCode) => {
    try {
      const res = await fetch(`${API_BASE}/courts?state_code=${stateCode}&dist_code=${distCode}&complex_code=${complexCode}`);
      const data = await res.json();
      if (data.success) setCourts(data.data);
    } catch {
      showError('Failed to fetch courts');
    }
  };

  const handleStateChange = (e) => {
    const code = e.target.value;
    setSelectedState(code);
    setSelectedDistrict('');
    setSelectedComplex('');
    setSelectedCourt('');
    setDistricts([]);
    setComplexes([]);
    setCourts([]);
    if (code) fetchDistricts(code);
  };

  const handleDistrictChange = (e) => {
    const code = e.target.value;
    setSelectedDistrict(code);
    setSelectedComplex('');
    setSelectedCourt('');
    setComplexes([]);
    setCourts([]);
    if (code) fetchComplexes(selectedState, code);
  };

  const handleComplexChange = (e) => {
    const code = e.target.value;
    setSelectedComplex(code);
    setSelectedCourt('');
    setCourts([]);
    if (code) fetchCourts(selectedState, selectedDistrict, code);
  };

  const formatDate = (dateStr) => {
    const [y, m, d] = dateStr.split('-');
    return `${d}-${m}-${y}`;
  };

  async function fetchCauseList() {
    if (!selectedState || !selectedDistrict || !selectedComplex || !selectedCourt) {
      showError('Please select all court details');
      return;
    }
    if (!selectedCourt.includes('^')) {
      showError('Please reselect Court (internal id missing).');
      await fetchCourts(selectedState, selectedDistrict, selectedComplex);
      return;
    }
    if (!captchaCode) {
      showError('Please enter captcha');
      return;
    }

    setLoading(true);
    setError('');
    setCauseList(null);

    try {
      const res = await fetch(`${API_BASE}/causelist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          state_code: selectedState,
          dist_code: selectedDistrict,
          court_complex_code: selectedComplex,
          court_code: selectedCourt,
          date: formatDate(selectedDate),
          case_type: caseKind,
          captcha_code: captchaCode
        })
      });

      if (!res.ok) {
        await handleApiError(res);
        return;
      }

      const data = await res.json();
      if (!data.success) {
        showError(data.message || 'Failed to fetch cause list');
        return;
      }

      if (data.data.total_cases === 0) {
        showError('No cases found for selected criteria');
      } else {
        setCauseList(data.data);
        showSuccess(`Found ${data.data.total_cases} cases`);
      }
    } catch {
      showError('Network error');
    } finally {
      setLoading(false);
    }
  }

  const downloadPDF = async () => {
    if (!selectedState || !selectedDistrict || !selectedComplex || !selectedCourt) {
      showError('Please select all court details');
      return;
    }
    if (!selectedCourt.includes('^')) {
      showError('Please reselect Court (internal id missing).');
      await fetchCourts(selectedState, selectedDistrict, selectedComplex);
      return;
    }
    if (!captchaCode) {
      showError('Please enter captcha');
      return;
    }
    setLoading(true);
    try {
      const cleanCourtName = (selectedCourtName || '').replace(/<[^>]*>/g, '').trim();
      const res = await fetch(`${API_BASE}/causelist/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          state_code: selectedState,
          dist_code: selectedDistrict,
          court_complex_code: selectedComplex,
          court_code: selectedCourt,
          date: formatDate(selectedDate),
          case_type: caseKind,
          captcha_code: captchaCode,
          court_name_txt: cleanCourtName,
        })
      });
      if (res.ok && res.headers.get('Content-Type')?.startsWith('application/pdf')) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `causelist_${formatDate(selectedDate)}.pdf`;
        a.click();
        window.URL.revokeObjectURL(url);
        showSuccess('PDF downloaded successfully');
      } else {
        await handleApiError(res);
      }
    } catch {
      showError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const downloadAll = async () => {
    if (!selectedState || !selectedDistrict || !selectedComplex) {
      showError('Please select state, district, and complex');
      return;
    }
    if (!captchaCode) {
      showError('Please enter captcha');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/causelist/pdf/all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          state_code: selectedState,
          dist_code: selectedDistrict,
          court_complex_code: selectedComplex,
          date: formatDate(selectedDate),
          case_type: caseKind,
          captcha_code: captchaCode,
        }),
      });
      if (res.ok && res.headers.get('Content-Type')?.startsWith('application/zip')) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `causelist_all_${formatDate(selectedDate)}.zip`;
        a.click();
        window.URL.revokeObjectURL(url);
        showSuccess('ZIP downloaded');
      } else {
        await handleApiError(res);
      }
    } catch {
      showError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    if (!selectedCourt) {
      showError('Please select a court');
      return;
    }

    if (!captchaCode) {
      showError('Enter captcha');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/stats`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          state_code: selectedState,
          dist_code: selectedDistrict,
          court_complex_code: selectedComplex,
          court_code: selectedCourt,
          date: formatDate(selectedDate),
          case_type: caseKind,
          captcha_code: captchaCode
        })
      });

      if (!res.ok) {
        await handleApiError(res);
        setLoading(false);
        return;
      }

      const data = await res.json();
      if (data.success) {
        setStatsData(data.data.purposes || {});
        showSuccess('Stats loaded');
      } else {
        showError(data.message || 'Stats failed');
      }
    } finally {
      setLoading(false);
    }
  };

  async function searchCNR() {
    if (!cnr.trim()) {
      showError('Please enter CNR number');
      return;
    }
    if (!captchaCode) {
      showError('Please enter captcha');
      return;
    }

    setLoading(true);
    setError('');
    setCaseDetails(null);

    try {
      const res = await fetch(`${API_BASE}/search/cnr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cnr: cnr.trim(), captcha_code: captchaCode })
      });

      if (!res.ok) {
        await handleApiError(res);
        return;
      }

      const data = await res.json();
      if (data.success) {
        setCaseDetails(data.data);
        showSuccess('Case found');
      } else {
        showError(data.message || 'Case not found');
      }
    } catch {
      showError('Network error');
    } finally {
      setLoading(false);
    }
  }

  const showError = (msg) => {
    setError(msg);
    setTimeout(() => setError(''), 5000);
  };

  const showSuccess = (msg) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(''), 3000);
  };

  const rows = causeList ? causeList.cases.filter(c => {
    const q = filter.toLowerCase();
    return !q ||
      (c.case_number || '').toLowerCase().includes(q) ||
      (c.parties || '').toLowerCase().includes(q) ||
      (c.purpose || '').toLowerCase().includes(q);
  }) : [];

  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-50 via-teal-50 to-cyan-50">
      <div className="bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <FileText className="w-8 h-8" />
            <div>
              <h1 className="text-3xl font-bold">eCourts India</h1>
              <p className="text-emerald-100 text-sm">Cause List Download System</p>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="max-w-7xl mx-auto px-4 mt-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
            <p className="text-red-800">{error}</p>
          </div>
        </div>
      )}

      {success && (
        <div className="max-w-7xl mx-auto px-4 mt-4">
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-center gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
            <p className="text-green-800">{success}</p>
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="grid md:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-200">
            <div className="flex items-center gap-2 mb-6">
              <MapPin className="w-5 h-5 text-emerald-600" />
              <h2 className="text-xl font-bold text-gray-800">Select Court</h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">State</label>
                <select
                  value={selectedState}
                  onChange={handleStateChange}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                >
                  <option value="">Select State</option>
                  {states.map(s => (
                    <option key={s.code} value={s.code}>{s.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">District</label>
                <select
                  value={selectedDistrict}
                  onChange={handleDistrictChange}
                  disabled={!selectedState}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:bg-gray-100"
                >
                  <option value="">Select District</option>
                  {districts.map(d => (
                    <option key={d.code} value={d.code}>{d.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Court Complex</label>
                <select
                  value={selectedComplex}
                  onChange={handleComplexChange}
                  disabled={!selectedDistrict}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:bg-gray-100"
                >
                  <option value="">Select Complex</option>
                  {complexes.map(c => (
                    <option key={c.code} value={c.code}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Court</label>
                <select
                  value={selectedCourt}
                  onChange={(e) => setSelectedCourt(e.target.value)}
                  disabled={!selectedComplex}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:bg-gray-100"
                >
                  <option value="">Select Court</option>
                  {courts.map(c => (
                    <option key={c.code} value={c.code}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Type</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="ck"
                      value="civ"
                      checked={caseKind === 'civ'}
                      onChange={(e) => setCaseKind(e.target.value)}
                      className="text-emerald-600 focus:ring-emerald-500"
                    />
                    Civil
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="ck"
                      value="crim"
                      checked={caseKind === 'crim'}
                      onChange={(e) => setCaseKind(e.target.value)}
                      className="text-emerald-600 focus:ring-emerald-500"
                    />
                    Criminal
                  </label>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Date</label>
                <div className="relative">
                  <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Captcha</label>
                <div className="flex items-center gap-3">
                  {captchaSrc ? (
                    <img 
                      key={captchaSrc} 
                      src={captchaSrc} 
                      alt="captcha" 
                      className="h-12 rounded border border-gray-300"
                      onError={() => setTimeout(refreshCaptcha, 300)}
                    />
                  ) : (
                    <div className="h-12 w-32 bg-gray-100 rounded animate-pulse" />
                  )}
                  <button
                    type="button"
                    onClick={refreshCaptcha}
                    className="px-3 py-2 bg-gray-200 hover:bg-gray-300 rounded transition flex items-center gap-1"
                  >
                    <RefreshCw className="w-4 h-4" />
                    Refresh
                  </button>
                </div>
                <input
                  type="text"
                  value={captchaCode}
                  onChange={(e) => setCaptchaCode(e.target.value)}
                  placeholder="Enter captcha"
                  className="mt-2 w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                />
              </div>

              <div className="flex gap-2 pt-4">
                <button
                  onClick={fetchCauseList}
                  disabled={loading}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Search className="w-5 h-5" />}
                  Fetch
                </button>
                <button
                  onClick={downloadPDF}
                  disabled={loading || !selectedCourt || !captchaCode}
                  className="flex-1 bg-teal-600 hover:bg-teal-700 text-white font-medium py-3 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  <Download className="w-5 h-5" />
                  PDF
                </button>
                <button
                  onClick={downloadAll}
                  disabled={loading || !captchaCode}
                  className="flex-1 bg-cyan-600 hover:bg-cyan-700 text-white font-medium py-3 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  <Download className="w-5 h-5" />
                  ZIP
                </button>
              </div>

              <button
                onClick={fetchStats}
                disabled={loading || !selectedCourt || !captchaCode}
                className="w-full bg-purple-600 hover:bg-purple-700 text-white font-medium py-2 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50 mt-2"
              >
                <BarChart3 className="w-4 h-4" />
                Stats
              </button>
              {statsData && (
                <div className="mt-6 p-4 bg-purple-50 border border-purple-200 rounded-lg">
                  <h3 className="font-bold text-gray-800 mb-3">Advocate cases</h3>
                  <ul className="space-y-1 text-sm">
                    {Object.entries(statsData).sort((a, b) => b[1] - a[1]).map(([purpose, count]) => (
                      <li key={purpose} className="flex justify-between">
                        <span className="font-medium text-purple-700">{purpose}</span>
                        <span className="text-gray-700">{count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-200">
            <div className="flex items-center gap-2 mb-6">
              <Search className="w-5 h-5 text-emerald-600" />
              <h2 className="text-xl font-bold text-gray-800">Case Search</h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">CNR Number</label>
                <input
                  type="text"
                  value={cnr}
                  onChange={(e) => setCnr(e.target.value)}
                  placeholder="Enter CNR (e.g., MHAU01999992015)"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                />
              </div>

              <button
                onClick={searchCNR}
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Search className="w-5 h-5" />}
                Search Case
              </button>

              {caseDetails && (
                <div className="mt-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
                  <h3 className="font-bold text-gray-800 mb-3">Case Details</h3>
                  <div className="space-y-2 text-sm">
                    <div><span className="font-medium">Case Number:</span> {caseDetails.case_number || 'N/A'}</div>
                    <div><span className="font-medium">Case Type:</span> {caseDetails.case_type || 'N/A'}</div>
                    <div><span className="font-medium">Filing Date:</span> {caseDetails.filing_date || 'N/A'}</div>
                    <div><span className="font-medium">Petitioner:</span> {caseDetails.petitioner || 'N/A'}</div>
                    <div><span className="font-medium">Respondent:</span> {caseDetails.respondent || 'N/A'}</div>
                    {caseDetails.is_listed_today && (
                      <div className="bg-green-100 text-green-800 px-3 py-2 rounded font-medium mt-3">
                        Listed Today - Serial No: {caseDetails.serial_number}
                      </div>
                    )}
                    {caseDetails.is_listed_tomorrow && (
                      <div className="bg-blue-100 text-blue-800 px-3 py-2 rounded font-medium mt-3">
                        Listed Tomorrow - Serial No: {caseDetails.serial_number}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {causeList && (
        <div className="max-w-7xl mx-auto px-4 mb-8">
          <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-200">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-gray-800">
                Cause List - {causeList.date}
              </h2>
              <div className="text-sm text-gray-600">
                Total Cases: <span className="font-bold text-emerald-600">{causeList.total_cases}</span>
              </div>
            </div>

            <div className="mb-4 flex items-center gap-3">
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by case number / party name / advocate"
                className="w-full max-w-md px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
              />
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-emerald-600 text-white">
                  <tr>
                    <th className="px-4 py-3 text-left">Sr No</th>
                    <th className="px-4 py-3 text-left">Cases</th>
                    <th className="px-4 py-3 text-left">Party Name</th>
                    <th className="px-4 py-3 text-left">Advocate</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c, i) => {
                    const prevSection = i > 0 ? rows[i - 1].section : null;
                    const showSection = c.section && c.section !== prevSection;
                    
                    return (
                      <React.Fragment key={i}>
                        {showSection && (
                          <tr>
                            <td colSpan={4} className="px-4 py-2 bg-blue-50 text-blue-700 font-semibold border-t-2 border-blue-200">
                              {c.section}
                            </td>
                          </tr>
                        )}
                        <tr className="hover:bg-emerald-50 transition border-b border-gray-200">
                          <td className="px-4 py-3">{c.serial_number}</td>
                          <td className="px-4 py-3">
                            <div className="font-medium">{c.case_number}</div>
                            {c.next_hearing && (
                              <div className="text-xs text-gray-600 mt-1">Next hearing date: {c.next_hearing}</div>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-pre-line leading-relaxed">{c.parties}</td>
                          <td className="px-4 py-3 whitespace-pre-line leading-relaxed">{c.purpose}</td>
                        </tr>
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <div className="bg-gradient-to-r from-emerald-600 to-teal-600 text-white py-4 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm">
          <p>eCourts India Cause List Scraper</p>
        </div>
      </div>
    </div>
  );
}