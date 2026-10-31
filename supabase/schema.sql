-- New data schema. Paste into Supabase dashboard > SQL Editor > Run. Order is FK-safe.
CREATE TABLE customers (
  customer_id                 VARCHAR(10) PRIMARY KEY,   -- C1001
  first_name                  VARCHAR(50),
  email_address               VARCHAR(100),
  snapshot_date               DATE,
  tenure_months               INT,
  plan_type                   VARCHAR(20),               -- Postpaid
  plan_id                     VARCHAR(10),               -- PP599
  plan_price                  DECIMAL(10,2),
  account_status              VARCHAR(10),               -- active / suspended / closed
  preferred_language          VARCHAR(5),                -- en
  activity_unit               VARCHAR(20),               -- sessions
  last_activity_days          INT,
  activity_30d                INT,
  activity_prev_30d           INT,
  loyalty_points              INT,
  loyalty_tier                VARCHAR(20),               -- Gold
  loyalty_points_expiry_date  DATE,
  on_time_payments_last_12    INT,
  bills_issued_last_12        INT
);

CREATE TABLE billing (
  bill_id                     VARCHAR(20) PRIMARY KEY,   -- B-202610-C1001
  customer_id                 VARCHAR(10) REFERENCES customers(customer_id),
  bill_status                 VARCHAR(10),               -- paid / due / overdue
  amount_due                  DECIMAL(10,2),
  amount_paid                 DECIMAL(10,2),
  currency                    CHAR(3),                   -- INR
  due_date                    DATE,
  last_payment_date           DATE NULL,
  autopay_enabled             BOOLEAN,
  dispute_open                BOOLEAN,
  dispute_opened_date         DATE NULL,
  payment_arrangement_active  BOOLEAN,
  hardship_flag               BOOLEAN
  -- overdue_days: DERIVED (snapshot_date - due_date), not stored
);

CREATE TABLE consent (
  customer_id                 VARCHAR(10) PRIMARY KEY REFERENCES customers(customer_id),
  email_allowed               BOOLEAN,
  marketing_consent           BOOLEAN,
  service_consent             BOOLEAN,
  consent_updated_at          DATE,
  email_status                VARCHAR(12),               -- valid / bounced / unverified
  open_complaint              BOOLEAN
);

CREATE TABLE contact_history (
  message_id                  VARCHAR(10) PRIMARY KEY,   -- M-0457
  customer_id                 VARCHAR(10) REFERENCES customers(customer_id),
  sent_at                     DATE,
  channel                     VARCHAR(10),               -- email
  message_type                VARCHAR(30),               -- payment_reminder
  segment                     VARCHAR(30),               -- payment reminder
  template_id                 VARCHAR(15),               -- TPL-PR-01
  offer_id                    VARCHAR(15) NULL,
  bill_id                     VARCHAR(20) NULL REFERENCES billing(bill_id),
  outcome                     VARCHAR(12)                -- delivered / opened / bounced / complained
  -- last_contacted_days_ago: DERIVED (snapshot_date - latest sent_at), not stored
);

CREATE TABLE offer_catalog (
  offer_id                    VARCHAR(15) PRIMARY KEY,   -- OFR-RWD-500
  offer_name                  VARCHAR(60),
  message_type                VARCHAR(30),               -- reward_offer
  eligible_segments           VARCHAR(60),
  plan_type                   VARCHAR(20),               -- postpaid / prepaid / any
  min_tenure_months           INT,
  channel                     VARCHAR(10),               -- email / sms
  value                       DECIMAL(10,2),
  value_unit                  VARCHAR(20),               -- INR_bill_credit / loyalty_points
  terms                       VARCHAR(200),
  valid_from                  DATE,
  expiry_date                 DATE,
  priority                    INT
);
