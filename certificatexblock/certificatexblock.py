# -*- coding: utf-8 -*-
import logging
import pkg_resources
from webob import Response
from xblock.core import XBlock
from xblock.fields import Integer, Scope, String, Boolean
from xblock.fragment import Fragment

from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from django.conf import settings
from django.template import Context, Template
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey

from lms.djangoapps.certificates import api as certs_api
from lms.djangoapps.certificates.utils import get_certificate_url
from common.djangoapps.student.models import CourseEnrollment
from lms.djangoapps.grades.api import CourseGradeFactory


log = logging.getLogger("cetificatexblock")


class CertificateXBlock(XBlock):
    """
    TO-DO: document what your XBlock does.
    """

    # Fields are defined on the class.  You can access them in your code as
    # self.<fieldname>.

    display_name = String(
        display_name=_("Display Name"),
        default="Certificate",
        scope=Scope.settings,
        help="The display name for this component.",
    )

    send_email = Boolean(
        display_name=_("Send Cetificate link email"),
        default=False,
        scope=Scope.settings,
        help="Select True if you want to send certificate link into email.",
    )
    icon_class = String(
        default="problem",
        scope=Scope.settings,
    )

    def resource_string(self, path):
        """Handy helper for getting resources from our kit."""
        data = pkg_resources.resource_string(__name__, path)
        return data.decode("utf8")

    def load_resource(self, resource_path):
        """
        Gets the content of a resource
        """
        resource_content = pkg_resources.resource_string(__name__, resource_path)
        return unicode(resource_content)

    def render_template(self, template_path, context={}):
        """
        Evaluate a template by resource path, applying the provided context
        """
        template_str = self.load_resource(template_path)
        return Template(template_str).render(Context(context))

    @XBlock.json_handler
    def studio_submit(self, data, suffix=""):
        """
        Called when submitting the form in Studio.
        """
        self.display_name = data.get("display_name")
        enable_email = data.get("enable_email")
        self.send_email = True if enable_email == "True" else False
        return Response(json_body={"result": "success"})

    def studio_view(self, context):
        """
        The view for editing the AudioXBlock parameters inside Studio.
        """
        context = {"display_name": self.display_name, "enable_email": self.send_email}
        html = self.render_template("static/html/certificatexblock_edit.html", context)
        frag = Fragment(html)
        frag.add_css(self.resource_string("static/css/certificatexblock_edit.css"))
        js = self.resource_string("static/js/src/certificatexblock_edit.js")
        frag.add_javascript(js)
        frag.initialize_js("CertificateXBlockEdit")
        return frag

    # TO-DO: change this view to display your data your own way.
    def student_view(self, context=None):
        """
        The primary view of the CertificateXBlock, shown to students
        when viewing courses.
        """
        html = self.resource_string("static/html/certificatexblock.html")
        template = Template(html)
        enable_submit_button = True
        student = User.objects.get(pk=self.runtime.user_id)
        try:
            certificate_status = certs_api.certificate_downloadable_status(
                student, self.runtime.course_id
            )
            if certificate_status["is_downloadable"]:
                enable_submit_button = False
        except Exception as e:
            log.info(str(e))

        html_data = template.render(
            Context(
                {
                    "enable_submit_button": enable_submit_button,
                }
            )
        )
        frag = Fragment(html_data.format(self=self))
        frag.add_css(self.resource_string("static/css/certificatexblock.css"))
        frag.add_javascript(self.resource_string("static/js/src/certificatexblock.js"))
        frag.initialize_js("CertificateXBlock")
        return frag

    # TO-DO: change this handler to perform your own actions.  You may need more
    # than one handler, or you may not need any handlers at all.
    @XBlock.handler
    def generate_certificate(self, data, suffix=""):
        is_cert_available = False
        cert_redirect_url = ""
        from courseware.views.views import (
            _track_successful_certificate_generation,
            _get_cert_data,
        )

        student = User.objects.get(pk=self.runtime.user_id)
        course_key = self.runtime.course_id
        course = modulestore().get_course(course_key, depth=2)
        enrollment_mode, _ = CourseEnrollment.enrollment_mode_for_user(
            student, course_key
        )
        course_grade = CourseGradeFactory().read(student, course)
        certificate_data = _get_cert_data(
            student, course, enrollment_mode, course_grade
        )
        if certificate_data:
            certificate_status = certs_api.certificate_downloadable_status(
                student, course.id
            )
            if certificate_status["is_downloadable"]:
                is_cert_available = True
                cert_redirect_url = (
                    settings.LMS_ROOT_URL + certificate_status["download_url"]
                )
                message = "Die Teilnahmebescheinigung ist bereits erstellt worden. ┃ The certificate has already been created."
            elif certificate_status["is_generating"]:
                message = "Die Teilnahmebescheinigung wird erstellt ┃ Certificate is being created."
            else:
                certs_api.generate_user_certificates(
                    student, course.id, course=course, generation_mode="self"
                )
                _track_successful_certificate_generation(student.id, course.id)
                is_cert_available = True
                cert_redirect_url = settings.LMS_ROOT_URL + get_certificate_url(
                    student.id, course_key
                )
                message = "Herzlichen Glückwunsch! Sie haben den Kurs erfolgreich abgeschlossen. ┃ Congratulations! You have successfully completed the training course."
                if self.send_email:
                    self.send_certificate_email(student, cert_redirect_url, course)

        else:
            message = "Die Teilnahmebescheinigung konnte nicht ausgestellt werden. Sie haben die erforderliche Punktzahl nicht erreicht. Bitte stellen Sie sicher, dass Sie alle Testfragen beantwortet haben.┃ The certificate was not issued. You have not reached the required score. Please make sure you have answered all test questions."

        return Response(
            json_body={
                "is_cert_available": is_cert_available,
                "cert_redirect_url": cert_redirect_url,
                "message": message,
            }
        )

    def send_certificate_email(self, student, cert_redirect_url, course):
        from student.tasks import send_activation_email

        context = {
            "username": student.profile.name or student.username,
            "course_name": course.display_name,
            "cert_link": cert_redirect_url,
            "platform_name": settings.PLATFORM_NAME,
        }
        message = self.render_template("static/email/certificate_email.txt", context)
        subject = "Congratulations!, You earned course certificate."
        send_activation_email.delay(
            subject, message, settings.DEFAULT_FROM_EMAIL, student.email
        )

    # TO-DO: change this to create the scenarios you'd like to see in the
    # workbench while developing your XBlock.

    @staticmethod
    def workbench_scenarios():
        """A canned scenario for display in the workbench."""
        return [
            (
                "CertificateXBlock",
                """<certificatexblock/>
             """,
            ),
            (
                "Multiple CertificateXBlock",
                """<vertical_demo>
                <certificatexblock/>
                <certificatexblock/>
                <certificatexblock/>
                </vertical_demo>
             """,
            ),
        ]
