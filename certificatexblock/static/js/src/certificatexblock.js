/* Javascript for CertificateXBlock. */
function CertificateXBlock(runtime, element) {
    var modal = $("#responseModal")
    $(document.body).on('click', '.final-submit', function(event){
        var handlerUrl = runtime.handlerUrl(element, 'generate_certificate');
        data = {}
        $.post(handlerUrl, data).done(function(response) {
            $(".retry-msg").html(response.message)
            if(response.is_cert_available){
                window.open(response.cert_redirect_url, '_blank');
                $(".closeModal").addClass("hidden")
            }else{
                modal.css("display", "block");
                $(".certificate-redirect").addClass('hidden')
                $(".closeModal").removeClass("hidden")
            }
        })    
    });
    $(document.body).on('click', '.closeModal', function(event){
        modal.css("display", "none");
    });
    $(document.body).on('click', '.certificate-redirect', function(event){
        modal.css("display", "none");
    });
}
