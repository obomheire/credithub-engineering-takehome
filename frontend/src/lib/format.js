export const ngn = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  maximumFractionDigits: 2,
});

export const LOAN_LABEL = {
  active: "Active",
  paid_off: "Paid off",
  cancelled: "Cancelled",
  written_off: "Written off",
};

export const PAY_LABEL = { pending: "Pending", applied: "Applied", rejected: "Rejected" };

export const REASON_LABEL = {
  unknown_loan: "Unknown loan",
  loan_not_active: "Loan not active",
  invalid_amount: "Invalid amount",
  overpayment: "Overpayment",
  duplicate_external_ref: "Duplicate",
};
