import React from "react";
import { NavLink } from "react-router-dom";

export default function NavBar() {
  return (
    <div className="topbar">
      <div className="brand">
        <h1>CreditHub</h1>
        <span className="tag">· Loan Servicing</span>
      </div>
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? "navlink active" : "navlink")}>
          Feed
        </NavLink>
        <NavLink to="/admin" className={({ isActive }) => (isActive ? "navlink active" : "navlink")}>
          Admin
        </NavLink>
      </nav>
    </div>
  );
}
