from mangum import Mangum

from .app import aws_app

handler = Mangum(aws_app(), lifespan="off")
