from flask_restx import Namespace, Resource
from db_plugins.db.sql import models
from .models import object_list_item, object_list, object_item
from .parsers import create_parsers
from sqlalchemy import text
from astropy import units
import argparse
from werkzeug.exceptions import NotFound
from ...db import db

api = Namespace("objects", description="Objects related operations")
api.models[object_list_item.name] = object_list_item
api.models[object_list.name] = object_list
api.models[object_item.name] = object_item

filter_parser, conesearch_parser, order_parser, pagination_parser = create_parsers()


@api.route("/")
@api.response(200, "Success")
@api.response(404, "Not found")
class ObjectList(Resource):
    @api.doc("list_object")
    @api.expect(filter_parser, conesearch_parser, pagination_parser, order_parser)
    @api.marshal_with(object_list)
    def get(self):
        """List all objects by given filters"""

        page = self.create_result_page(
            filter_parser, conesearch_parser, pagination_parser, order_parser
        )

        serialized_items = self.serialize_items(page.items)

        if len(serialized_items):
            return {
                "total": page.total,
                "page": page.page,
                "next": page.next_num,
                "has_next": page.has_next,
                "prev": page.prev_num,
                "has_prev": page.has_prev,
                "items": serialized_items,
            }
        else:
            raise NotFound("Objects not found")

    def serialize_items(self, data):
        ret = []
        for obj, clf in data:
            obj = {**obj.__dict__}
            clf = {**clf.__dict__} if clf else {}
            ret.append({**obj, **clf})
        return ret

    def create_result_page(
        self, filter_parser, conesearch_parser, pagination_parser, order_parser
    ):
        filter_args = filter_parser.parse_args()
        conesearch_args = conesearch_parser.parse_args()
        pagination_args = pagination_parser.parse_args()
        order_args = order_parser.parse_args()
        filters = self._parse_filters(filter_args)
        conesearch_args = self._convert_conesearch_args(conesearch_args)
        conesearch = self._create_conesearch_statement(conesearch_args)
        query = self._get_objects(filters, conesearch, conesearch_args)
        order_statement = self._create_order_statement(query, order_args)
        query = query.order_by(order_statement)
        return query.paginate(
            pagination_args["page"],
            pagination_args["page_size"],
            pagination_args["count"],
        )

    def _get_objects(self, filters, conesearch, conesearch_args):
        return (
            db.query(models.Object, models.Classification)
            .outerjoin(models.Object.classifications)
            .filter(*filters)
            .params(**conesearch_args)
        )

    def _create_order_statement(self, query, args):
        statement = None
        cols = query.column_descriptions
        order_by = args["order_by"]
        if order_by:
            for col in cols:
                model = col["type"]
                attr = getattr(model, order_by, None)
                if attr:
                    statement = attr
                    break
            order_mode = args["order_mode"]
            if order_mode:
                if order_mode == "ASC":
                    statement = attr.asc()
                if order_mode == "DESC":
                    statement = attr.desc()
        return statement

    def _parse_filters(self, args):
        classifier, class_, ndet, firstmjd, lastmjd, probability = (
            True,
            True,
            True,
            True,
            True,
            True,
        )
        if args["classifier"]:
            classifier = models.Classification.classifier_name == args["classifier"]
        if args["class"]:
            class_ = models.Classification.class_name == args["class"]
        if args["ndet"]:
            ndet = models.Object.ndet >= args["ndet"][0]
            if len(args["ndet"]) > 1:
                ndet = ndet & (models.Object.ndet <= args["ndet"][1])
        if args["firstmjd"]:
            firstmjd = models.Object.firstmjd >= args["firstmjd"][0]
            if len(args["firstmjd"]) > 1:
                firstmjd = firstmjd & (
                    models.Object.firstmjd <= args["firstmjd"][1]
                )
        if args["lastmjd"]:
            lastmjd = models.Object.lastmjd >= args["lastmjd"][0]
            if len(args["lastmjd"]) > 1:
                lastmjd = lastmjd & (models.Object.lastmjd <= args["lastmjd"][1])
        if args["probability"]:
            probability = models.Classification.probability >= args["probability"]

        return classifier, class_, ndet, firstmjd, lastmjd, probability

    def _create_conesearch_statement(self, args):
        try:
            ra, dec, radius = args["ra"], args["dec"], args["radius"]
        except KeyError:
            ra, dec, radius = None, None, None

        if ra and dec and radius:
            return text("q3c_radial_query(meanra, meandec,:ra, :dec, :radius)")
        else:
            return True

    def _convert_conesearch_args(self, args):
        try:
            ra, dec, radius = args["ra"], args["dec"], args["radius"]
        except KeyError:
            ra, dec, radius = None, None, None

        if ra and dec and radius:
            radius = radius * units.arcsec
            radius = radius.to(units.deg)
            radius = radius.value
        return {"ra": ra, "dec": dec, "radius": radius}


@api.route("/<id>")
@api.param("id", "The object's identifier")
@api.response(200, "Success")
@api.response(404, "Object not found")
class Object(Resource):
    @api.doc("get_object")
    @api.marshal_with(object_item)
    def get(self, id):
        """Fetch an object given its identifier"""
        result = (
            db.query(models.Object)
            .filter(models.Object.oid == id)
            .one_or_none()
        )
        if result:
            return result
        else:
            raise NotFound("Object not found")