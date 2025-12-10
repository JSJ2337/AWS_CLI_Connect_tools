--
-- Licensed to the Apache Software Foundation (ASF) under one
-- or more contributor license agreements.  See the NOTICE file
-- distributed with this work for additional information
-- regarding copyright ownership.  The ASF licenses this file
-- to you under the Apache License, Version 2.0 (the
-- "License"); you may not use this file except in compliance
-- with the License.  You may obtain a copy of the License at
--
--   http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing,
-- software distributed under the License is distributed on an
-- "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
-- KIND, either express or implied.  See the License for the
-- specific language governing permissions and limitations
-- under the License.
--

-- Create enum types
CREATE TYPE guacamole_entity_type AS ENUM(
    'USER',
    'USER_GROUP'
);

CREATE TYPE guacamole_system_permission_type AS ENUM(
    'CREATE_CONNECTION',
    'CREATE_CONNECTION_GROUP',
    'CREATE_SHARING_PROFILE',
    'CREATE_USER',
    'CREATE_USER_GROUP',
    'ADMINISTER'
);

CREATE TYPE guacamole_object_permission_type AS ENUM(
    'READ',
    'UPDATE',
    'DELETE',
    'ADMINISTER'
);

--
-- Table of entities. Each entity has a corresponding unique ID.
--
CREATE TABLE guacamole_entity (

  entity_id     SERIAL  NOT NULL,
  name          VARCHAR(128) NOT NULL,
  type          guacamole_entity_type NOT NULL,

  PRIMARY KEY (entity_id),
  UNIQUE (type, name)

);

--
-- Table of users. Each user has a unique username and various optional
-- properties.
--
CREATE TABLE guacamole_user (

  user_id       SERIAL      NOT NULL,
  entity_id     INTEGER     NOT NULL,

  -- Optionally-salted password
  password_hash BYTEA       NOT NULL,
  password_salt BYTEA,
  password_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Account disabled/expired status
  disabled      BOOLEAN     NOT NULL DEFAULT FALSE,
  expired       BOOLEAN     NOT NULL DEFAULT FALSE,

  -- Time-based access restriction
  access_window_start    TIME,
  access_window_end      TIME,

  -- Date-based access restriction
  valid_from  DATE,
  valid_until DATE,

  -- Timezone used for all date/time comparisons and interpretation
  timezone VARCHAR(64),

  -- Profile information
  full_name           VARCHAR(256),
  email_address       VARCHAR(256),
  organization        VARCHAR(128),
  organizational_role VARCHAR(128),

  PRIMARY KEY (user_id),

  CONSTRAINT guacamole_user_single_entity
    UNIQUE (entity_id),

  CONSTRAINT guacamole_user_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id)
    ON DELETE CASCADE

);

--
-- Table of user groups. Each user group may have an arbitrary set of member
-- users and member groups, with those members inheriting the permissions
-- granted to that group.
--
CREATE TABLE guacamole_user_group (

  user_group_id SERIAL      NOT NULL,
  entity_id     INTEGER     NOT NULL,

  -- Group disabled status
  disabled      BOOLEAN     NOT NULL DEFAULT FALSE,

  PRIMARY KEY (user_group_id),

  CONSTRAINT guacamole_user_group_single_entity
    UNIQUE (entity_id),

  CONSTRAINT guacamole_user_group_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id)
    ON DELETE CASCADE

);

--
-- Table of user group members. Each entry represents the membership of a
-- user or user group in a particular user group.
--
CREATE TABLE guacamole_user_group_member (

  user_group_id    INTEGER NOT NULL,
  member_entity_id INTEGER NOT NULL,

  PRIMARY KEY (user_group_id, member_entity_id),

  CONSTRAINT guacamole_user_group_member_parent
    FOREIGN KEY (user_group_id)
    REFERENCES guacamole_user_group (user_group_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_user_group_member_entity
    FOREIGN KEY (member_entity_id)
    REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE

);

--
-- Table of connection groups. Each connection group has a unique name.
--
CREATE TABLE guacamole_connection_group (

  connection_group_id   SERIAL       NOT NULL,
  parent_id             INTEGER,
  connection_group_name VARCHAR(128) NOT NULL,
  type                  VARCHAR(32)  NOT NULL
                        DEFAULT 'ORGANIZATIONAL',

  -- Concurrency limits
  max_connections          INTEGER,
  max_connections_per_user INTEGER,
  enable_session_affinity  BOOLEAN NOT NULL DEFAULT FALSE,

  PRIMARY KEY (connection_group_id),

  CONSTRAINT guacamole_connection_group_parent
    FOREIGN KEY (parent_id)
    REFERENCES guacamole_connection_group (connection_group_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_connection_group_name_parent
    UNIQUE (connection_group_name, parent_id)

);

--
-- Table of connections. Each connection has a unique name and is
-- associated with a parent connection group.
--
CREATE TABLE guacamole_connection (

  connection_id       SERIAL       NOT NULL,
  connection_name     VARCHAR(128) NOT NULL,
  parent_id           INTEGER,
  protocol            VARCHAR(32)  NOT NULL,

  -- Guacamole proxy (guacd) overrides
  proxy_port              INTEGER,
  proxy_hostname          VARCHAR(512),
  proxy_encryption_method VARCHAR(4),

  -- Concurrency limits
  max_connections          INTEGER,
  max_connections_per_user INTEGER,

  -- Connection weight
  connection_weight INTEGER,
  failover_only     BOOLEAN NOT NULL DEFAULT FALSE,

  PRIMARY KEY (connection_id),

  CONSTRAINT guacamole_connection_parent
    FOREIGN KEY (parent_id)
    REFERENCES guacamole_connection_group (connection_group_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_connection_name_parent
    UNIQUE (connection_name, parent_id)

);

--
-- Table of base entities which may each be either a user or user group.
-- Other tables which represent qualities shared by both users and groups
-- will point to guacamole_entity, while tables which represent qualities
-- specific to users or groups will point to guacamole_user or
-- guacamole_user_group.
--
CREATE TABLE guacamole_sharing_profile (

  sharing_profile_id    SERIAL       NOT NULL,
  sharing_profile_name  VARCHAR(128) NOT NULL,
  primary_connection_id INTEGER      NOT NULL,

  PRIMARY KEY (sharing_profile_id),

  CONSTRAINT guacamole_sharing_profile_name
    UNIQUE (sharing_profile_name),

  CONSTRAINT guacamole_sharing_profile_connection
    FOREIGN KEY (primary_connection_id)
    REFERENCES guacamole_connection (connection_id)
    ON DELETE CASCADE

);

--
-- Table of connection parameters. Each parameter is simply a name/value pair
-- associated with a connection.
--
CREATE TABLE guacamole_connection_parameter (

  connection_id   INTEGER       NOT NULL,
  parameter_name  VARCHAR(128)  NOT NULL,
  parameter_value VARCHAR(4096),

  PRIMARY KEY (connection_id, parameter_name),

  CONSTRAINT guacamole_connection_parameter_connection
    FOREIGN KEY (connection_id)
    REFERENCES guacamole_connection (connection_id) ON DELETE CASCADE

);

--
-- Table of sharing profile parameters. Each parameter is simply a name/value
-- pair associated with a sharing profile. These parameters dictate the
-- restrictions/features which apply to the tunnel created when the sharing
-- profile is used.
--
CREATE TABLE guacamole_sharing_profile_parameter (

  sharing_profile_id INTEGER       NOT NULL,
  parameter_name     VARCHAR(128)  NOT NULL,
  parameter_value    VARCHAR(4096),

  PRIMARY KEY (sharing_profile_id, parameter_name),

  CONSTRAINT guacamole_sharing_profile_parameter_sharing_profile
    FOREIGN KEY (sharing_profile_id)
    REFERENCES guacamole_sharing_profile (sharing_profile_id) ON DELETE CASCADE

);

--
-- Table of arbitrary user attributes. Each attribute is simply a name/value
-- pair associated with a user. Arbitrary attributes are defined by other
-- extensions. Attributes defined by this extension will be mapped to
-- properly-typed columns of a specific table.
--
CREATE TABLE guacamole_user_attribute (

  user_id         INTEGER       NOT NULL,
  attribute_name  VARCHAR(128)  NOT NULL,
  attribute_value VARCHAR(4096),

  PRIMARY KEY (user_id, attribute_name),

  CONSTRAINT guacamole_user_attribute_user
    FOREIGN KEY (user_id)
    REFERENCES guacamole_user (user_id) ON DELETE CASCADE

);

--
-- Table of arbitrary user group attributes. Each attribute is simply a
-- name/value pair associated with a user group. Arbitrary attributes are
-- defined by other extensions. Attributes defined by this extension will be
-- mapped to properly-typed columns of a specific table.
--
CREATE TABLE guacamole_user_group_attribute (

  user_group_id   INTEGER       NOT NULL,
  attribute_name  VARCHAR(128)  NOT NULL,
  attribute_value VARCHAR(4096),

  PRIMARY KEY (user_group_id, attribute_name),

  CONSTRAINT guacamole_user_group_attribute_user_group
    FOREIGN KEY (user_group_id)
    REFERENCES guacamole_user_group (user_group_id) ON DELETE CASCADE

);

--
-- Table of arbitrary connection attributes. Each attribute is simply a
-- name/value pair associated with a connection. Arbitrary attributes are
-- defined by other extensions. Attributes defined by this extension will be
-- mapped to properly-typed columns of a specific table.
--
CREATE TABLE guacamole_connection_attribute (

  connection_id   INTEGER       NOT NULL,
  attribute_name  VARCHAR(128)  NOT NULL,
  attribute_value VARCHAR(4096),

  PRIMARY KEY (connection_id, attribute_name),

  CONSTRAINT guacamole_connection_attribute_connection
    FOREIGN KEY (connection_id)
    REFERENCES guacamole_connection (connection_id) ON DELETE CASCADE

);

--
-- Table of arbitrary sharing profile attributes. Each attribute is simply a
-- name/value pair associated with a sharing profile. Arbitrary attributes
-- are defined by other extensions. Attributes defined by this extension will
-- be mapped to properly-typed columns of a specific table.
--
CREATE TABLE guacamole_sharing_profile_attribute (

  sharing_profile_id INTEGER       NOT NULL,
  attribute_name     VARCHAR(128)  NOT NULL,
  attribute_value    VARCHAR(4096),

  PRIMARY KEY (sharing_profile_id, attribute_name),

  CONSTRAINT guacamole_sharing_profile_attribute_sharing_profile
    FOREIGN KEY (sharing_profile_id)
    REFERENCES guacamole_sharing_profile (sharing_profile_id) ON DELETE CASCADE

);

--
-- Table of arbitrary connection group attributes. Each attribute is simply
-- a name/value pair associated with a connection group. Arbitrary attributes
-- are defined by other extensions. Attributes defined by this extension will
-- be mapped to properly-typed columns of a specific table.
--
CREATE TABLE guacamole_connection_group_attribute (

  connection_group_id INTEGER       NOT NULL,
  attribute_name      VARCHAR(128)  NOT NULL,
  attribute_value     VARCHAR(4096),

  PRIMARY KEY (connection_group_id, attribute_name),

  CONSTRAINT guacamole_connection_group_attribute_connection_group
    FOREIGN KEY (connection_group_id)
    REFERENCES guacamole_connection_group (connection_group_id) ON DELETE CASCADE

);

--
-- Table of system permissions. Each system permission grants a user or user
-- group a system-level privilege of some kind.
--
CREATE TABLE guacamole_system_permission (

  entity_id   INTEGER                           NOT NULL,
  permission  guacamole_system_permission_type  NOT NULL,

  PRIMARY KEY (entity_id, permission),

  CONSTRAINT guacamole_system_permission_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE

);

--
-- Table of connection permissions. Each connection permission grants a user
-- or user group a certain level of access to a connection.
--
CREATE TABLE guacamole_connection_permission (

  entity_id     INTEGER                         NOT NULL,
  connection_id INTEGER                         NOT NULL,
  permission    guacamole_object_permission_type NOT NULL,

  PRIMARY KEY (entity_id, connection_id, permission),

  CONSTRAINT guacamole_connection_permission_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_connection_permission_connection
    FOREIGN KEY (connection_id)
    REFERENCES guacamole_connection (connection_id) ON DELETE CASCADE

);

--
-- Table of connection group permissions. Each group permission grants a user
-- or user group a certain level of access to a connection group.
--
CREATE TABLE guacamole_connection_group_permission (

  entity_id           INTEGER                         NOT NULL,
  connection_group_id INTEGER                         NOT NULL,
  permission          guacamole_object_permission_type NOT NULL,

  PRIMARY KEY (entity_id, connection_group_id, permission),

  CONSTRAINT guacamole_connection_group_permission_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_connection_group_permission_connection_group
    FOREIGN KEY (connection_group_id)
    REFERENCES guacamole_connection_group (connection_group_id) ON DELETE CASCADE

);

--
-- Table of sharing profile permissions. Each sharing profile permission
-- grants a user or user group a certain level of access to a sharing profile.
--
CREATE TABLE guacamole_sharing_profile_permission (

  entity_id          INTEGER                         NOT NULL,
  sharing_profile_id INTEGER                         NOT NULL,
  permission         guacamole_object_permission_type NOT NULL,

  PRIMARY KEY (entity_id, sharing_profile_id, permission),

  CONSTRAINT guacamole_sharing_profile_permission_entity
    FOREIGN KEY (entity_id)
    REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE,

  CONSTRAINT guacamole_sharing_profile_permission_sharing_profile
    FOREIGN KEY (sharing_profile_id)
    REFERENCES guacamole_sharing_profile (sharing_profile_id) ON DELETE CASCADE

);

--
-- Table of connection history records. Each record defines a specific user's
-- session, including the connection used, the start time, and the end time
-- (if any).
--
CREATE TABLE guacamole_connection_history (

  history_id           SERIAL           NOT NULL,
  user_id              INTEGER,
  username             VARCHAR(128)     NOT NULL,
  remote_host          VARCHAR(256),
  connection_id        INTEGER,
  connection_name      VARCHAR(128)     NOT NULL,
  sharing_profile_id   INTEGER,
  sharing_profile_name VARCHAR(128),
  start_date           TIMESTAMPTZ      NOT NULL,
  end_date             TIMESTAMPTZ,

  PRIMARY KEY (history_id),

  CONSTRAINT guacamole_connection_history_user
    FOREIGN KEY (user_id)
    REFERENCES guacamole_user (user_id) ON DELETE SET NULL,

  CONSTRAINT guacamole_connection_history_connection
    FOREIGN KEY (connection_id)
    REFERENCES guacamole_connection (connection_id) ON DELETE SET NULL,

  CONSTRAINT guacamole_connection_history_sharing_profile
    FOREIGN KEY (sharing_profile_id)
    REFERENCES guacamole_sharing_profile (sharing_profile_id) ON DELETE SET NULL

);

--
-- Table of user history records. Each record defines a specific user's
-- session, including the username, the start time, and the end time
-- (if any).
--
CREATE TABLE guacamole_user_history (

  history_id           SERIAL           NOT NULL,
  user_id              INTEGER,
  username             VARCHAR(128)     NOT NULL,
  remote_host          VARCHAR(256),
  start_date           TIMESTAMPTZ      NOT NULL,
  end_date             TIMESTAMPTZ,

  PRIMARY KEY (history_id),

  CONSTRAINT guacamole_user_history_user
    FOREIGN KEY (user_id)
    REFERENCES guacamole_user (user_id) ON DELETE SET NULL

);

--
-- User password history
--
CREATE TABLE guacamole_user_password_history (

  password_history_id SERIAL       NOT NULL,
  user_id             INTEGER      NOT NULL,

  -- Salted password
  password_hash BYTEA        NOT NULL,
  password_salt BYTEA,
  password_date TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (password_history_id),

  CONSTRAINT guacamole_user_password_history_user
    FOREIGN KEY (user_id)
    REFERENCES guacamole_user (user_id) ON DELETE CASCADE

);

-- Create default user "guacadmin" with password "guacadmin"
INSERT INTO guacamole_entity (name, type) VALUES ('guacadmin', 'USER');
INSERT INTO guacamole_user (entity_id, password_hash, password_salt)
SELECT
    entity_id,
    decode('ca458a7d494e3be824f5e1e175a1556c0f8eef2d2d7e4fe52ca5da04ea710823', 'hex'),
    decode('fe24adc5e11e2b25288d4da7551a7bed', 'hex')
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

-- Grant admin permissions to guacadmin
INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'ADMINISTER'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'CREATE_CONNECTION'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'CREATE_CONNECTION_GROUP'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'CREATE_SHARING_PROFILE'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'CREATE_USER'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT entity_id, 'CREATE_USER_GROUP'
FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER';
