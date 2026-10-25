"""Storage adapters. AWS uses conditional writes and atomic review/map transactions."""
import copy
import json
from decimal import Decimal
from threading import RLock

from .models import initial_map


class Conflict(Exception):
    pass


class MemoryStore:
    mode = "local-memory-not-durable"

    def __init__(self):
        self.items = {}
        self.lock = RLock()
        self.map = initial_map()

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.items.get(key))

    def put_new(self, key, value):
        with self.lock:
            if key in self.items:
                raise Conflict("Resource already exists")
            self.items[key] = copy.deepcopy(value)

    def get_map(self):
        with self.lock:
            return copy.deepcopy(self.map)

    def list_reports(self, status, limit, cursor):
        with self.lock:
            keys = sorted(k for k in self.items if k.startswith("REPORT#") and
                          (not status or self.items[k]["status"] == status))
            keys = [k for k in keys if not cursor or k > cursor]
            page = keys[:limit]
            return {"items": [self.get(k) for k in page],
                    "next_cursor": page[-1] if len(keys) > limit else None}

    def review(self, key, report, expected_version, updated_map):
        with self.lock:
            if self.items[key]["status"] != "PENDING" or self.map["version"] != expected_version:
                raise Conflict("Report or map changed; refresh before reviewing")
            self.items[key] = copy.deepcopy(report)
            if updated_map is not None:
                self.map = copy.deepcopy(updated_map)


class MemoryPhotos:
    def __init__(self):
        self.photos = {}

    def put(self, photo_id, data):
        self.photos[photo_id] = data

    def url(self, photo_id):
        return f"/api/v2/photos/{photo_id}/content"


class DynamoStore:
    mode = "aws-dynamodb-s3"

    def __init__(self, table_name, resource=None):
        import boto3
        self.table = (resource or boto3.resource("dynamodb")).Table(table_name)
        self.client = self.table.meta.client
        try:
            self.put_new("MAP#prototype", initial_map())
        except Conflict:
            pass

    @staticmethod
    def _decimal(value):
        return json.loads(json.dumps(value), parse_float=Decimal)

    @staticmethod
    def _plain(item):
        return json.loads(json.dumps(item, default=lambda v: int(v) if v % 1 == 0 else float(v)))

    def get(self, key):
        item = self.table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
        if item is None:
            return None
        return self._plain(item["data"])

    def put_new(self, key, value):
        from botocore.exceptions import ClientError
        try:
            self.table.put_item(Item={"pk": key, "data": self._decimal(value)},
                                ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict("Resource already exists") from exc
            raise

    def get_map(self):
        return self.get("MAP#prototype")

    def list_reports(self, status, limit, cursor):
        # A bounded scan is sufficient for this small prototype. A continuation
        # cursor may be returned even for an empty filtered page: keep paging.
        from boto3.dynamodb.conditions import Attr
        filt = Attr("pk").begins_with("REPORT#")
        if status:
            filt = filt & Attr("data.status").eq(status)
        args = {"FilterExpression": filt, "Limit": limit, "ConsistentRead": True}
        if cursor:
            args["ExclusiveStartKey"] = {"pk": cursor}
        result = self.table.scan(**args)
        return {"items": [self._plain(i["data"]) for i in result["Items"]],
                "next_cursor": result.get("LastEvaluatedKey", {}).get("pk")}

    def review(self, key, report, expected_version, updated_map):
        from boto3.dynamodb.types import TypeSerializer
        from botocore.exceptions import ClientError
        serialize = TypeSerializer().serialize

        def attrs(value):
            return {k: serialize(v) for k, v in self._decimal(value).items()}

        operations = [{"Put": {"TableName": self.table.name,
            "Item": attrs({"pk": key, "data": report}),
            "ConditionExpression": "#d.#s = :pending",
            "ExpressionAttributeNames": {"#d": "data", "#s": "status"},
            "ExpressionAttributeValues": attrs({":pending": "PENDING"})}}]
        map_op = {"TableName": self.table.name,
                  "ConditionExpression": "#d.#v = :version",
                  "ExpressionAttributeNames": {"#d": "data", "#v": "version"},
                  "ExpressionAttributeValues": attrs({":version": expected_version})}
        if updated_map is None:
            map_op["Key"] = attrs({"pk": "MAP#prototype"})
            operations.append({"ConditionCheck": map_op})
        else:
            map_op["Item"] = attrs({"pk": "MAP#prototype", "data": updated_map})
            operations.append({"Put": map_op})
        try:
            # Resource clients install document marshallers; use a separate
            # low-level client for the already-serialized transaction payload.
            import boto3
            client = boto3.client("dynamodb", region_name=self.client.meta.region_name,
                                  endpoint_url=self.client.meta.endpoint_url)
            client.transact_write_items(TransactItems=operations)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])
                if any(r.get("Code") == "ConditionalCheckFailed" for r in reasons):
                    raise Conflict("Report or map changed; refresh before reviewing") from exc
            raise


class S3Photos:
    def __init__(self, bucket, client=None):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.client = client or boto3.client("s3", config=Config(signature_version="s3v4"))

    def put(self, photo_id, data):
        self.client.put_object(Bucket=self.bucket, Key=f"photos/{photo_id}.jpg",
                               Body=data, ContentType="image/jpeg",
                               ServerSideEncryption="AES256", IfNoneMatch="*")

    def url(self, photo_id):
        return self.client.generate_presigned_url("get_object", Params={
            "Bucket": self.bucket, "Key": f"photos/{photo_id}.jpg"}, ExpiresIn=300)
