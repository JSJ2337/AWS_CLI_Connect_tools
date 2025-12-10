-- Guacamole 데이터베이스 초기화 스크립트
-- 기본 스키마와 데이터를 생성합니다.

-- 1. 데이터베이스 스키마 생성 (Guacamole 표준 스키마)
CREATE TABLE IF NOT EXISTS guacamole_connection (
    connection_id    SERIAL       NOT NULL,
    connection_name  VARCHAR(128) NOT NULL,
    protocol         VARCHAR(32)  NOT NULL,
    PRIMARY KEY (connection_id),
    UNIQUE (connection_name)
);

CREATE TABLE IF NOT EXISTS guacamole_connection_parameter (
    connection_id   INTEGER       NOT NULL,
    parameter_name  VARCHAR(128)  NOT NULL,
    parameter_value VARCHAR(4096),
    PRIMARY KEY (connection_id, parameter_name),
    CONSTRAINT guacamole_connection_parameter_ibfk_1
        FOREIGN KEY (connection_id)
        REFERENCES guacamole_connection (connection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guacamole_user (
    user_id         SERIAL       NOT NULL,
    username        VARCHAR(128) NOT NULL,
    password_hash   BYTEA        NOT NULL,
    password_salt   BYTEA,
    password_date   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled        BOOLEAN      NOT NULL DEFAULT FALSE,
    expired         BOOLEAN      NOT NULL DEFAULT FALSE,
    access_window_start    TIME,
    access_window_end      TIME,
    valid_from      DATE,
    valid_until     DATE,
    timezone        VARCHAR(64),
    full_name       VARCHAR(256),
    email_address   VARCHAR(256),
    organization    VARCHAR(128),
    organizational_role VARCHAR(128),
    PRIMARY KEY (user_id),
    UNIQUE (username)
);

-- 2. 기본 관리자 사용자 생성
-- 사용자명: guacadmin, 비밀번호: guacadmin
INSERT INTO guacamole_user (username, password_hash, password_salt)
VALUES (
    'guacadmin',
    decode('ca458a7d494e3be824f5e1e175a1556c0f8eef2d2d7e4fe52ca5da04ea710823', 'hex'),
    decode('fe24adc5e11e2b25288d4da7551a7bed', 'hex')
) ON CONFLICT (username) DO NOTHING;

-- 3. 권한 테이블 생성
CREATE TABLE IF NOT EXISTS guacamole_connection_permission (
    user_id         INTEGER NOT NULL,
    connection_id   INTEGER NOT NULL,
    permission      VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, connection_id, permission),
    CONSTRAINT guacamole_connection_permission_ibfk_1
        FOREIGN KEY (connection_id)
        REFERENCES guacamole_connection (connection_id) ON DELETE CASCADE,
    CONSTRAINT guacamole_connection_permission_ibfk_2
        FOREIGN KEY (user_id)
        REFERENCES guacamole_user (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guacamole_system_permission (
    user_id         INTEGER NOT NULL,
    permission      VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, permission),
    CONSTRAINT guacamole_system_permission_ibfk_1
        FOREIGN KEY (user_id)
        REFERENCES guacamole_user (user_id) ON DELETE CASCADE
);

-- 4. 관리자에게 시스템 권한 부여
INSERT INTO guacamole_system_permission (user_id, permission)
SELECT user_id, 'ADMINISTER'
FROM guacamole_user
WHERE username = 'guacadmin'
ON CONFLICT (user_id, permission) DO NOTHING;

INSERT INTO guacamole_system_permission (user_id, permission)
SELECT user_id, 'CREATE_CONNECTION'
FROM guacamole_user
WHERE username = 'guacadmin'
ON CONFLICT (user_id, permission) DO NOTHING;