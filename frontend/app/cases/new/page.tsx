"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Header } from "../../components/Header";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Party = components["schemas"]["PartyCreate"];
const blank: Party = { name: "", gstin: "", pan: "", udyam_no: "", udyam_reg_date: "", enterprise_type: "", activity: "" };

function PartyFields({ title, value, onChange }: { title: string; value: Party; onChange: (value: Party) => void }) {
  const set = (key: keyof Party, next: string) => onChange({ ...value, [key]: next });
  return <fieldset><legend>{title}</legend><label>Name<input required value={value.name} onChange={(e) => set("name", e.target.value)} /></label><div className="form-grid"><label>GSTIN<input maxLength={15} value={value.gstin ?? ""} onChange={(e) => set("gstin", e.target.value.toUpperCase())} /></label><label>PAN<input maxLength={10} value={value.pan ?? ""} onChange={(e) => set("pan", e.target.value.toUpperCase())} /></label><label>Udyam number<input value={value.udyam_no ?? ""} onChange={(e) => set("udyam_no", e.target.value)} /></label><label>Udyam registration date<input type="date" value={value.udyam_reg_date ?? ""} onChange={(e) => set("udyam_reg_date", e.target.value)} /></label><label>Enterprise type<select value={value.enterprise_type ?? ""} onChange={(e) => set("enterprise_type", e.target.value)}><option value="">Select</option><option value="micro">Micro</option><option value="small">Small</option><option value="medium">Medium</option></select></label><label>Activity<select value={value.activity ?? ""} onChange={(e) => set("activity", e.target.value)}><option value="">Select</option><option value="manufacturer">Manufacturer</option><option value="service">Service</option><option value="trader">Trader</option></select></label></div></fieldset>;
}

export default function NewCasePage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [supplier, setSupplier] = useState<Party>(blank);
  const [buyer, setBuyer] = useState<Party>(blank);
  const [error, setError] = useState<string | null>(null);
  const validateParty = (party: Party) => {
    if (party.gstin && !/^[0-9A-Z]{15}$/.test(party.gstin)) return "GSTIN must be 15 letters and numbers.";
    if (party.pan && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(party.pan)) return "PAN must be 10 characters.";
    if (party.udyam_reg_date && Number.isNaN(new Date(party.udyam_reg_date).getTime())) return "Enter a valid Udyam registration date.";
    return null;
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null);
    const validation = validateParty(supplier) ?? validateParty(buyer);
    if (validation) { setError(validation); return; }
    try {
      const created = await apiClient<components["schemas"]["CaseRead"]>("/cases", { method: "POST", body: JSON.stringify({ title, supplier, buyer }) });
      router.push(`/cases/${created.id}`);
    } catch (err) { setError(err instanceof Error ? err.message : "Case could not be created."); }
  };
  return <><Header /><main className="page-shell narrow"><div className="page-heading"><div><p className="eyebrow">Cases</p><h1>New case</h1><p className="lede">Add the parties before uploading the transaction records.</p></div></div><form onSubmit={submit} className="form-panel"><label>Case title<input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Acme Components delayed payment" /></label><PartyFields title="Supplier" value={supplier} onChange={setSupplier} /><PartyFields title="Buyer" value={buyer} onChange={setBuyer} />{error && <div className="alert alert-error" role="alert">{error}</div>}<div className="form-actions"><button type="button" className="button" onClick={() => router.back()}>Cancel</button><button className="button button-dark" type="submit">Create case</button></div></form></main></>;
}
