// Ensure this script is loaded after Bootstrap JavaScript
$(document).ready(function () {
    console.log('Script executed!');
    
    // Customize the modal content when the document is ready
    customizeConfirmDeleteModal();
    
    // Function to customize the modal content
    function customizeConfirmDeleteModal() {
        var modalTitle = $('#confirmDeleteModal').find('.modal-title');
        var modalBody = $('#confirmDeleteModal').find('.modal-body');
        
        // Set the modal title and body content
        modalTitle.text('Confirm Delete');
        modalBody.text('Are you sure you want to delete this claim?');
    }
});
