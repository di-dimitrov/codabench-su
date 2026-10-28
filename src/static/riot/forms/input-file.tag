<!-- Field class on initial definition to keep Semantic UI styling -->
<input-file class="field {error: opts.error}">
    <!-- Default mode: the SINGLE FILE with NO OTHER OPTIONS example (a button and the name of the chosen file) -->
    <!-- In the future, we'll have this type AND a type that is pre-filled with nice options -->
    <div if="{ !opts.droppable }" class="ui left action file input" ref="submission_upload">
        <button type="button" class="ui icon button" onclick="{ open_file_selection }">
            <i class="attach icon"></i>
        </button>
        <input type="file" name="{ opts.name }" ref="file_input" accept="{ opts.accept }">

        <!-- Just showing the file after it is uploaded -->
        <input ref="file_input_display" readonly onclick="{ open_file_selection }">
    </div>

    <!--
        Drop zone mode (attribute droppable="true"): drag and drop or click to browse. The file is checked as soon as it
        is chosen (a .zip name, a real zip archive, a single file) but nothing is uploaded: the form that contains this
        component decides when, usually from a Submit button. It reads the chosen file from `this.file` and listens
        for the jQuery events `file_valid` and `file_cleared` that are triggered on the file input.
    -->
    <div if="{ opts.droppable }">
        <input type="file" name="{ opts.name }" ref="file_input" accept="{ opts.accept }" style="display: none">
        <div class="drop-zone { dragging: dragging, 'has-file': file, 'has-error': file_error }"
             tabindex="0"
             role="button"
             onclick="{ browse }"
             onkeydown="{ key_browse }">
            <virtual if="{ !file }">
                <i class="cloud upload icon"></i>
                <div class="drop-title">Drag &amp; drop your .zip file here</div>
                <div class="drop-hint">or click to browse</div>
            </virtual>
            <virtual if="{ file }">
                <i class="file archive outline icon"></i>
                <div class="drop-title">{ file.name }</div>
                <div class="drop-hint">{ readable_size(file.size) }</div>
                <button type="button" class="ui mini basic red button remove-file" onclick="{ remove }">
                    <i class="close icon"></i> Remove
                </button>
            </virtual>
        </div>
        <div if="{ file_error }" class="ui red message">{ file_error }</div>
    </div>

    <script>
        var self = this

        // Drop zone state
        self.file = null          // the chosen file, once it passed the checks
        self.file_error = null    // why the last chosen file(s) were refused
        self.dragging = false

        // First bytes of a zip archive: normal archive, empty archive, split archive
        var ZIP_SIGNATURES = ['504b0304', '504b0506', '504b0708']

        /*---------------------------------------------------------------------
         Init
        ---------------------------------------------------------------------*/
        self.one("mount", function () {
            if (self.opts.droppable) {
                $(self.refs.file_input).on('change', function () {
                    var files = Array.from(self.refs.file_input.files)
                    // Empty the input so choosing the same file again fires 'change' again
                    self.refs.file_input.value = ''
                    self.handle_files(files)
                })
                // Capture phase, so nothing on the page can stop these events before we see them
                window.addEventListener('dragover', self.on_window_dragover, true)
                window.addEventListener('dragleave', self.on_window_dragleave, true)
                window.addEventListener('drop', self.on_window_drop, true)
                return
            }

            // clean up name displaying
            $(self.refs.file_input)
                .on('change', function (event) {
                    // Value comes like c:/fakepath/file_name.txt -- cut out everything but file_name.txt
                    self.refs.file_input_display.value = self.refs.file_input.value.replace(/\\/g, '/').replace(/.*\//, '')
                    self.update()
                })
                .on('click', function() {
                    // Set the value of the input to null so the 'change' event fires even if the same
                    // file is selected!
                    self.refs.file_input.value = null
                })
        })

        /*---------------------------------------------------------------------
         Methods
        ---------------------------------------------------------------------*/
        self.open_file_selection = function () {
            self.refs.file_input.click()
            // Re-enable the button after 5 seconds
            self.refs.submission_upload.style['display'] = 'none'
            setTimeout(function () {
                self.refs.submission_upload.style['display'] = ''
            }, 6000);
        }

        /*---------------------------------------------------------------------
         Drop zone
        ---------------------------------------------------------------------*/
        self.browse = function () {
            self.refs.file_input.click()
        }

        self.key_browse = function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                self.refs.file_input.click()
                return
            }
            // Any other key keeps its normal behaviour (Tab must still move the focus)
            return true
        }

        /*
         Dropping a file on a page makes the browser open the file, unless the 'dragover' and 'drop' events are
         cancelled first. That is done here, on the whole window and before anything else, so even a drop that misses
         the zone (or an error further down) can never make the browser leave the page. A file that is dropped
         anywhere on the page while the zone is on screen is taken as dropped on the zone.
        */
        self.has_files = function (event) {
            var types = event.dataTransfer && event.dataTransfer.types
            return !!types && Array.prototype.indexOf.call(types, 'Files') !== -1
        }

        // offsetParent is null when the zone, or something around it such as another tab, is hidden
        self.zone_is_visible = function () {
            return !!self.root.offsetParent
        }

        self.on_window_dragover = function (event) {
            if (!self.has_files(event)) {
                return
            }
            event.preventDefault()
            try {
                event.dataTransfer.dropEffect = 'copy'
            } catch (error) {
                // not every browser lets this be set, the drop still works
            }
            if (self.zone_is_visible() && !self.dragging) {
                self.dragging = true
                self.update()
            }
        }

        self.on_window_dragleave = function (event) {
            // Only when the pointer leaves the browser window; moving between elements also fires 'dragleave'
            if (self.dragging && event.relatedTarget === null) {
                self.dragging = false
                self.update()
            }
        }

        self.on_window_drop = function (event) {
            if (!self.has_files(event)) {
                return
            }
            event.preventDefault()
            self.dragging = false
            try {
                if (self.zone_is_visible()) {
                    self.take_dropped(event.dataTransfer)
                }
            } catch (error) {
                console.error(error)
                self.refuse('The dropped file could not be read: ' + error.message)
            }
            self.update()
        }

        self.take_dropped = function (transfer) {
            // Folders have to be recognised now, the dropped items are not available once the event is over
            var dropped_folder = _.some(transfer.items || [], function (item) {
                var entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null
                return entry && entry.isDirectory
            })
            if (dropped_folder) {
                self.refuse('Folders cannot be submitted. Please zip it first and drop the .zip file.')
                return
            }
            self.handle_files(Array.from(transfer.files))
        }

        self.on('unmount', function () {
            window.removeEventListener('dragover', self.on_window_dragover, true)
            window.removeEventListener('dragleave', self.on_window_dragleave, true)
            window.removeEventListener('drop', self.on_window_drop, true)
        })

        self.remove = function (event) {
            // The button is inside the drop zone, do not open the file browser as well
            event.stopPropagation()
            self.clear()
        }

        // Forget the chosen file (also called by the form after a submission)
        self.clear = function () {
            self.file = null
            self.file_error = null
            if (self.refs.file_input) {
                self.refs.file_input.value = ''
                $(self.refs.file_input).trigger('file_cleared')
            }
            self.update()
        }

        self.refuse = function (message) {
            self.file = null
            self.file_error = message
            $(self.refs.file_input).trigger('file_cleared')
            toastr.error(message)
            self.update()
        }

        self.handle_files = function (files) {
            self.file_error = null
            if (files.length === 0) {
                return
            }
            if (files.length > 1) {
                self.refuse('Only one file can be submitted at a time, but ' + files.length + ' files were selected.')
                return
            }
            var file = files[0]
            self.check_file(file).then(function (error) {
                if (error) {
                    self.refuse(error)
                    return
                }
                self.file = file
                self.file_error = null
                $(self.refs.file_input).trigger('file_valid', [file])
                self.update()
            })
        }

        // Resolves to a message when the file is refused, or to null when it can be used
        self.check_file = function (file) {
            if (!/\.zip$/i.test(file.name)) {
                return Promise.resolve('"' + file.name + '" is not a .zip file. Only .zip files can be submitted.')
            }
            if (file.size === 0) {
                return Promise.resolve('"' + file.name + '" is empty.')
            }
            return new Promise(function (resolve) {
                var reader = new FileReader()
                reader.onload = function () {
                    var signature = Array.from(new Uint8Array(reader.result)).map(function (byte) {
                        return ('0' + byte.toString(16)).slice(-2)
                    }).join('')
                    if (ZIP_SIGNATURES.indexOf(signature) === -1) {
                        resolve('"' + file.name + '" has a .zip name but is not a valid zip archive. ' +
                            'Please create the zip again and retry.')
                    } else {
                        resolve(null)
                    }
                }
                reader.onerror = function () {
                    resolve('"' + file.name + '" could not be read. Please select it again.')
                }
                reader.readAsArrayBuffer(file.slice(0, 4))
            })
        }

        self.readable_size = function (bytes) {
            if (bytes < 1024) {
                return bytes + ' B'
            }
            var units = ['KB', 'MB', 'GB', 'TB']
            var unit = -1
            do {
                bytes = bytes / 1024
                unit++
            } while (bytes >= 1024 && unit < units.length - 1)
            return bytes.toFixed(1) + ' ' + units[unit]
        }
    </script>
    <style>
        /* Make this component "div like" */
        :scope {
            display: block;
        }

        .drop-zone {
            border: 2px dashed #b3b3b3;
            border-radius: 6px;
            padding: 1.5em 1em;
            text-align: center;
            cursor: pointer;
            background: #fafafa;
            transition: border-color 0.15s, background 0.15s;
            outline: none;
        }

        .drop-zone:hover,
        .drop-zone:focus {
            border-color: #2185d0;
        }

        .drop-zone.dragging {
            border-color: #2185d0;
            background: #eaf4ff;
        }

        .drop-zone.has-file {
            border-style: solid;
            border-color: #21ba45;
            background: #f6fff8;
        }

        .drop-zone.has-error {
            border-color: #db2828;
            background: #fff6f6;
        }

        .drop-zone .icon {
            display: block;
            margin: 0 auto 0.25em;
            font-size: 2em;
            color: #888;
        }

        .drop-title {
            font-weight: bold;
            word-break: break-all;
        }

        .drop-hint {
            margin-top: 0.25em;
            color: #777;
        }

        .drop-zone .remove-file {
            margin-top: 0.75em;
        }

        .ui.red.message {
            margin-top: 0.5em;
        }
    </style>
</input-file>
