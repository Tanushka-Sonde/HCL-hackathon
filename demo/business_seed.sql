-- Synthetic business dataset for the SQL tool (fictional company, fictional people).
-- Note: there is intentionally NO vendor_invoices table; the vendor_invoices
-- tool template exists to demonstrate the controlled tool-failure path.

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    budget_usd INTEGER NOT NULL,
    spent_usd INTEGER NOT NULL
);

CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE assignments (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    allocation_pct INTEGER NOT NULL,
    PRIMARY KEY (project_id, employee_id)
);

INSERT INTO projects VALUES
 ('PRJ-1001', 'Atlas Analytics Platform', 'Engineering', 'Asha Rao', 'active', 420000, 310500),
 ('PRJ-1002', 'Helios Data Migration', 'Finance', 'Daniel Okafor', 'active', 250000, 238000),
 ('PRJ-1003', 'Nimbus Cloud Cost Optimisation', 'IT Operations', 'Mei Lin', 'active', 180000, 64000),
 ('PRJ-1004', 'Orion Customer Portal', 'Engineering', 'Lucas Ferreira', 'on hold', 300000, 121000),
 ('PRJ-1005', 'Vega HR Self-Service', 'Human Resources', 'Priya Nair', 'completed', 95000, 91200);

INSERT INTO employees VALUES
 ('E-001', 'Asha Rao', 'Engineering', 'Engineering Manager'),
 ('E-002', 'Tom Becker', 'Engineering', 'Data Engineer'),
 ('E-003', 'Sara Haddad', 'Engineering', 'Platform Engineer'),
 ('E-004', 'Kenji Watanabe', 'Engineering', 'QA Engineer'),
 ('E-005', 'Daniel Okafor', 'Finance', 'Finance Systems Lead'),
 ('E-006', 'Elena Petrova', 'Finance', 'Business Analyst'),
 ('E-007', 'Mei Lin', 'IT Operations', 'Cloud Architect'),
 ('E-008', 'Lucas Ferreira', 'Engineering', 'Product Owner'),
 ('E-009', 'Priya Nair', 'Human Resources', 'HR Systems Lead'),
 ('E-010', 'Omar Siddiqui', 'IT Operations', 'FinOps Analyst');

INSERT INTO assignments VALUES
 ('PRJ-1001', 'E-001', 50), ('PRJ-1001', 'E-002', 100), ('PRJ-1001', 'E-003', 100), ('PRJ-1001', 'E-004', 50),
 ('PRJ-1002', 'E-005', 80), ('PRJ-1002', 'E-006', 100), ('PRJ-1002', 'E-002', 20),
 ('PRJ-1003', 'E-007', 60), ('PRJ-1003', 'E-010', 100),
 ('PRJ-1004', 'E-008', 50), ('PRJ-1004', 'E-004', 50),
 ('PRJ-1005', 'E-009', 30);
