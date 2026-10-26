# Deployment inventory, authentication and cleanup

This inventory began as pre-deployment guidance. The subsequent team demo's
resource names and recorded AWS checks are in [DEPLOYMENT.md](DEPLOYMENT.md).
Use [README.md](README.md) for build/deploy commands and the live evidence gate.

## Resource inventory

| Logical resource | Purpose | Removal behaviour |
| --- | --- | --- |
| HttpApi and JWT authorizer | AWS-hosted `/api/v2` routes, restricted dashboard CORS, throttling | Stack-managed |
| ApiFunction and generated IAM role | FastAPI/Mangum handler, resource-scoped storage access | Stack-managed |
| StateTable | Reports plus one-to-one tickets, authoritative versioned map, photo metadata | Retained on stack deletion |
| PhotosBucket and bucket policy | Private, encrypted evidence JPEGs, seven-day lifecycle, HTTPS-only | Bucket retained on stack deletion |
| FunctionLogs | Lambda operational audit messages, seven-day log retention | Stack-managed |
| SAM artifact bucket | Deployment packages created/used by SAM guided deployment | Separate from evidence; inspect ownership |
| Trusted identity provider | Sign-in and JWT access tokens | External prerequisite; not created by this template |

The function role permits GetItem, PutItem, Scan and ConditionCheckItem only on
the StateTable ARN. DynamoDB transactions authorize the actions for their
individual items. S3 GetObject/PutObject is limited to this bucket's `photos/*`.
ListBucket is limited to this one bucket and lets S3 return missing-object 404s
instead of ambiguous 403s. CloudWatch logging is added by the SAM execution role.
No Bedrock, COOL, IoT, SNS or OpenCV runtime is deployed by this template.

Before a live upload, agree on retention/privacy with the owner. Current
configuration is seven-day photos, seven-day operational logs, indefinite
report/review metadata. There is no automatic image redaction. Local SQLite
files are development data and do not have S3 lifecycle deletion; local photo
access still expires according to metadata. Remove local state deliberately
when finished with the demo.

## Authentication setup using Cognito (one supported option)

The API accepts a trusted OIDC issuer. These steps describe the Cognito option;
confirm service availability and cost within your account plan first.

1. Create a user pool in the approved region. For this private prototype, disable
   public self-sign-up; create only the camera, reviewer and laptop test users
   you intend to authorize. Use separate camera and reviewer users.
2. Create a resource server with identifier `pathable` and scopes `camera`,
   `reviewer`, `map`. The resulting scope names are `pathable/camera`,
   `pathable/reviewer`, `pathable/map`.
3. Create a **public** app client without a secret. Enable authorization-code
   flow and these scopes plus `openid`. Configure exact callback/logout URLs
   with Persons 1 and 3. Use PKCE S256; do not embed a secret or implement a
   password collection screen in their clients. Configure the managed-login
   domain and use its authorization endpoint.
4. A single public app client can be used for this bounded demo. Request only the
   scope each client needs. Scope availability alone does not assign a reviewer:
   the API independently checks camera `sub` and the reviewer subject allowlist.
   A camera user requesting a reviewer scope is still forbidden. The camera and
   reviewer subjects cannot overlap. Map scope grants reads of the prototype map.
5. Take the non-secret user-pool issuer URL and app client ID from Cognito. Supply
   them to SAM as `JwtIssuer` and `JwtAudience`. Use the camera user's `sub` as
   `CameraSubject`, reviewer users' `sub` values as `ReviewerSubjects`, and the
   dashboard origin as `DashboardOrigin`. Never send their passwords to chat.
6. Clients use **access tokens** in `Authorization: Bearer ...`, not ID tokens.
   API Gateway verifies signature, issuer, audience/client ID and required
   scopes. The backend takes identity only from that verified gateway context;
   it does not decode an unverified client header into an identity.
7. Perform the unauthorized/role-separation tests in the deployed API before
   publishing an endpoint as ready. Browser S3 upload CORS currently permits the
   dashboard origin. A native Python camera does not require browser CORS. If
   a separate browser camera origin is needed, coordinate that configuration
   before deployment rather than opening CORS to every origin.

Temporary developer AWS login (SSO or an approved role) is separate from these
application-user tokens. Use the normal AWS SDK credential chain; do not put
AWS access keys in the dashboard, camera payload, repository or logs.

## Operational logs and persistence checks

CloudWatch receives JSON events for upload slots, stored base64-upload photos,
pending reports, duplicate report/review retries, committed decisions, map
updates and service-error types. Entries carry event/ticket IDs and map versions;
review commits also record authenticated reviewer `sub`. Notes, signed URLs,
bearer tokens and image bytes are excluded. The durable report/ticket is the
authoritative review audit record; logs are useful diagnostics and may be
missing if the process stops immediately after a database commit. AWS failures
must be checked against stored state before assuming that a retry is new work.

The report and its ticket share **one DynamoDB item**, keyed by event ID, with a
deterministic `T-<event_id>` ticket ID. They cannot diverge or duplicate on retry.
Review updates that item together with a conditional map update in one
transaction. For rejection, the transaction checks the current map version
without replacing the map. No report or ticket alone is an approved closure.

Local restart test launches a separate Python process against SQLite and disk
photos. Moto tests create fresh DynamoDB/S3 adapters. Neither establishes actual
AWS durability; repeat the fresh-process reads with deployed credentials and
inspect real DynamoDB/S3 before declaring deployment complete.

## Cleanup instructions — do not run until the owner is finished

1. Stop camera submissions and laptop polling. Save any permitted test evidence
   and record which account, region and stack you are removing. Do not export
   secrets or retain personal images without permission.
2. Inspect the stack's Resources and Outputs tabs. Record the exact table and
   bucket names, and determine whether the identity provider or artifact bucket
   is shared. Do not remove shared resources.
3. Delete the dedicated stack from CloudFormation, or run `sam delete` with its
   exact stack name, profile and region and review its confirmation. This removes
   stack-managed API/function/role/log resources. Inspect deletion results.
4. The table and photo bucket are intentionally retained. After an explicit
   decision to discard their data, delete that exact DynamoDB table. Empty the
   exact evidence bucket and delete it through the S3 console. Stack deletion
   alone does not remove these resources or guarantee that charges stop.
5. Remove the dedicated Cognito pool/domain/client and dedicated SAM artifact
   objects/bucket only if this project owns them and nobody else uses them.
6. Recheck the resource inventory and billing in the selected region/account.
   Remaining retained resources, backups or artifacts may still cost money.

## Official references

- [S3 presigned URL checksums and expiry](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
- [DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
- [Cognito custom scopes](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html)
- [Cognito authorization code and PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html)
- [API Gateway JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)
